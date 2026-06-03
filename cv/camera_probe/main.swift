import Foundation
import AVFoundation
import CoreImage
import CoreGraphics
import ImageIO
import Network
import UniformTypeIdentifiers

let defaultSnapshotPath = "cv/captures/latest.jpg"

func log(_ message: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    print("[\(stamp)] \(message)")
    fflush(stdout)
}

extension Data {
    mutating func appendString(_ string: String) {
        self.append(Data(string.utf8))
    }
}

struct Config {
    var port: UInt16 = 8765
    var mock = false
    var snapshotPath = defaultSnapshotPath
    var snapshotInterval: TimeInterval = 0.5
    var fps: Double = 10.0
}

func parseConfig() -> Config {
    var config = Config()
    let args = Array(CommandLine.arguments.dropFirst())
    var index = 0

    func value(after flag: String) -> String {
        let next = index + 1
        guard next < args.count else {
            fputs("Missing value for \(flag)\n", stderr)
            exit(64)
        }
        index += 1
        return args[next]
    }

    while index < args.count {
        let arg = args[index]
        switch arg {
        case "--mock":
            config.mock = true
        case "--port":
            let raw = value(after: arg)
            guard let parsed = UInt16(raw) else {
                fputs("Invalid --port: \(raw)\n", stderr)
                exit(64)
            }
            config.port = parsed
        case "--snapshot-path":
            config.snapshotPath = value(after: arg)
        case "--snapshot-interval":
            let raw = value(after: arg)
            guard let parsed = Double(raw), parsed > 0 else {
                fputs("Invalid --snapshot-interval: \(raw)\n", stderr)
                exit(64)
            }
            config.snapshotInterval = parsed
        case "--fps":
            let raw = value(after: arg)
            guard let parsed = Double(raw), parsed > 0 else {
                fputs("Invalid --fps: \(raw)\n", stderr)
                exit(64)
            }
            config.fps = parsed
        case "--help", "-h":
            print("""
            Lisbon Camera Bridge

            Options:
              --port N                  HTTP port, default 8765
              --mock                    Generate synthetic frames instead of opening camera
              --snapshot-path PATH      Latest JPEG path, default \(defaultSnapshotPath)
              --snapshot-interval SEC   Snapshot write interval, default 0.5
              --fps N                   Camera/mock encode FPS, default 10

            Endpoints:
              GET /health
              GET /status
              GET /frame.jpg
              GET /stream.mjpeg
            """)
            exit(0)
        default:
            fputs("Unknown argument: \(arg)\n", stderr)
            exit(64)
        }
        index += 1
    }

    return config
}

struct FrameSnapshot {
    let jpeg: Data
    let width: Int
    let height: Int
    let device: String
    let frameCount: UInt64
    let createdAt: Date
}

final class FrameStore {
    private let lock = NSLock()
    private var latestFrame: FrameSnapshot?
    private var lastError: String?
    private var startedAt = Date()

    func update(jpeg: Data, width: Int, height: Int, device: String) {
        lock.lock()
        let nextCount = (latestFrame?.frameCount ?? 0) + 1
        latestFrame = FrameSnapshot(jpeg: jpeg,
                                    width: width,
                                    height: height,
                                    device: device,
                                    frameCount: nextCount,
                                    createdAt: Date())
        lastError = nil
        lock.unlock()
    }

    func setError(_ message: String) {
        lock.lock()
        lastError = message
        lock.unlock()
    }

    func snapshot() -> FrameSnapshot? {
        lock.lock()
        let frame = latestFrame
        lock.unlock()
        return frame
    }

    func status(mode: String, port: UInt16) -> [String: Any] {
        lock.lock()
        let frame = latestFrame
        let error = lastError
        let uptimeMs = Int(Date().timeIntervalSince(startedAt) * 1000)
        lock.unlock()

        var payload: [String: Any] = [
            "ok": frame != nil,
            "service": "lisbon-camera-bridge",
            "mode": mode,
            "port": Int(port),
            "uptimeMs": uptimeMs,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ]

        if let frame {
            payload["device"] = frame.device
            payload["width"] = frame.width
            payload["height"] = frame.height
            payload["frameCount"] = Int(frame.frameCount)
            payload["latestFrameAgeMs"] = Int(Date().timeIntervalSince(frame.createdAt) * 1000)
        } else {
            payload["device"] = NSNull()
            payload["width"] = NSNull()
            payload["height"] = NSNull()
            payload["frameCount"] = 0
            payload["latestFrameAgeMs"] = NSNull()
        }

        if let error {
            payload["error"] = error
        }

        return payload
    }
}

func jsonData(_ payload: [String: Any]) -> Data {
    do {
        return try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
    } catch {
        return Data("{\"ok\":false,\"error\":\"json serialization failed\"}".utf8)
    }
}

final class SnapshotWriter {
    private let store: FrameStore
    private let path: String
    private let interval: TimeInterval
    private let queue = DispatchQueue(label: "lisbon.camera.snapshot-writer")
    private var timer: DispatchSourceTimer?
    private var lastWrittenFrameCount: UInt64 = 0

    init(store: FrameStore, path: String, interval: TimeInterval) {
        self.store = store
        self.path = path
        self.interval = interval
    }

    func start() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: interval)
        timer.setEventHandler { [weak self] in
            self?.writeIfNeeded()
        }
        self.timer = timer
        timer.resume()
        log("snapshot writer enabled at \(path), every \(interval)s")
    }

    private func writeIfNeeded() {
        guard let frame = store.snapshot(), frame.frameCount != lastWrittenFrameCount else { return }
        do {
            let url = URL(fileURLWithPath: path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try frame.jpeg.write(to: url, options: [.atomic])
            lastWrittenFrameCount = frame.frameCount
        } catch {
            store.setError("snapshot write failed: \(error)")
        }
    }
}

final class MockFrameSource {
    private let store: FrameStore
    private let fps: Double
    private let queue = DispatchQueue(label: "lisbon.camera.mock-source")
    private var timer: DispatchSourceTimer?
    private var frameNumber: UInt64 = 0

    init(store: FrameStore, fps: Double) {
        self.store = store
        self.fps = fps
    }

    func start() {
        let interval = 1.0 / fps
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: interval)
        timer.setEventHandler { [weak self] in
            self?.emitFrame()
        }
        self.timer = timer
        timer.resume()
        log("mock frame source started at \(fps) fps")
    }

    private func emitFrame() {
        frameNumber += 1
        let width = 640
        let height = 360
        guard let jpeg = makeMockJPEG(width: width, height: height, frameNumber: frameNumber) else {
            store.setError("failed to generate mock JPEG")
            return
        }
        store.update(jpeg: jpeg, width: width, height: height, device: "mock-camera")
    }

    private func makeMockJPEG(width: Int, height: Int, frameNumber: UInt64) -> Data? {
        let bytesPerPixel = 4
        let bytesPerRow = width * bytesPerPixel
        var pixels = [UInt8](repeating: 0, count: height * bytesPerRow)
        let movingBand = Int(frameNumber * 9) % max(width, 1)

        for y in 0..<height {
            for x in 0..<width {
                let offset = y * bytesPerRow + x * bytesPerPixel
                let dx = abs(x - movingBand)
                let pulse = max(0, 255 - dx * 4)
                pixels[offset] = UInt8((x * 255) / max(width - 1, 1))
                pixels[offset + 1] = UInt8((y * 255) / max(height - 1, 1))
                pixels[offset + 2] = UInt8((Int(frameNumber * 7) + pulse) % 256)
                pixels[offset + 3] = 255
            }
        }

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let provider = CGDataProvider(data: Data(pixels) as CFData)
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue)
        guard let provider,
              let image = CGImage(width: width,
                                  height: height,
                                  bitsPerComponent: 8,
                                  bitsPerPixel: 32,
                                  bytesPerRow: bytesPerRow,
                                  space: colorSpace,
                                  bitmapInfo: bitmapInfo,
                                  provider: provider,
                                  decode: nil,
                                  shouldInterpolate: false,
                                  intent: .defaultIntent) else {
            return nil
        }

        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else {
            return nil
        }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }
}

final class CameraCapture: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private let store: FrameStore
    private let fps: Double
    private let ciContext = CIContext()
    private let queue = DispatchQueue(label: "lisbon.camera.capture-frames")
    private var session: AVCaptureSession?
    private var deviceName = "unknown-camera"
    private var lastEncodeAt = Date.distantPast

    init(store: FrameStore, fps: Double) {
        self.store = store
        self.fps = fps
    }

    func startWhenAuthorized() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            start()
        case .notDetermined:
            store.setError("requesting camera permission")
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                if granted {
                    self?.start()
                } else {
                    self?.store.setError("camera permission denied")
                }
            }
        case .denied:
            store.setError("camera permission denied in System Settings > Privacy & Security > Camera")
        case .restricted:
            store.setError("camera permission restricted")
        @unknown default:
            store.setError("unknown camera permission state")
        }
    }

    private func selectDevice() -> AVCaptureDevice? {
        let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.external, .builtInWideAngleCamera],
                                                         mediaType: .video,
                                                         position: .unspecified)
        let devices = discovery.devices
        if let anker = devices.first(where: { device in
            device.localizedName.localizedCaseInsensitiveContains("Anker") ||
            device.localizedName.localizedCaseInsensitiveContains("PowerConf")
        }) {
            return anker
        }
        return devices.first ?? AVCaptureDevice.default(for: .video)
    }

    private func start() {
        guard let device = selectDevice() else {
            store.setError("no video capture device found")
            return
        }
        deviceName = device.localizedName

        do {
            let session = AVCaptureSession()
            session.sessionPreset = .hd1280x720
            let input = try AVCaptureDeviceInput(device: device)
            guard session.canAddInput(input) else {
                store.setError("cannot add camera input for \(device.localizedName)")
                return
            }
            session.addInput(input)

            let output = AVCaptureVideoDataOutput()
            output.alwaysDiscardsLateVideoFrames = true
            output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
            output.setSampleBufferDelegate(self, queue: queue)
            guard session.canAddOutput(output) else {
                store.setError("cannot add video output for \(device.localizedName)")
                return
            }
            session.addOutput(output)

            self.session = session
            DispatchQueue.global(qos: .userInitiated).async {
                session.startRunning()
            }
            log("camera capture started for \(device.localizedName) at up to \(fps) fps")
        } catch {
            store.setError("camera input failed for \(device.localizedName): \(error)")
        }
    }

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        let now = Date()
        guard now.timeIntervalSince(lastEncodeAt) >= (1.0 / fps) else { return }
        lastEncodeAt = now

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            store.setError("received sample without pixel buffer")
            return
        }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
        let options = [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.78]

        guard let jpeg = ciContext.jpegRepresentation(of: ciImage, colorSpace: colorSpace, options: options) else {
            store.setError("JPEG encoding failed")
            return
        }

        store.update(jpeg: jpeg, width: width, height: height, device: deviceName)
    }
}

final class HTTPServer {
    private let store: FrameStore
    private let mode: String
    private let port: UInt16
    private let queue = DispatchQueue(label: "lisbon.camera.http-server")
    private let listener: NWListener

    init(store: FrameStore, mode: String, port: UInt16) throws {
        self.store = store
        self.mode = mode
        self.port = port
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            throw NSError(domain: "LisbonCameraBridge", code: 1, userInfo: [NSLocalizedDescriptionKey: "invalid port"])
        }
        self.listener = try NWListener(using: .tcp, on: nwPort)
    }

    func start() {
        listener.stateUpdateHandler = { state in
            switch state {
            case .ready:
                log("HTTP camera bridge listening on http://127.0.0.1:\(self.port)")
            case .failed(let error):
                self.store.setError("HTTP listener failed: \(error)")
            default:
                break
            }
        }
        listener.newConnectionHandler = { [weak self] connection in
            self?.handle(connection)
        }
        listener.start(queue: queue)
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 16_384) { [weak self] data, _, _, error in
            guard let self else { return }
            guard error == nil, let data, let request = String(data: data, encoding: .utf8) else {
                connection.cancel()
                return
            }
            let firstLine = request.components(separatedBy: "\r\n").first ?? ""
            let parts = firstLine.split(separator: " ")
            guard parts.count >= 2 else {
                self.sendJSON(connection, status: "400 Bad Request", payload: ["ok": false, "error": "bad request"])
                return
            }
            let method = String(parts[0])
            let rawPath = String(parts[1])
            let path = rawPath.components(separatedBy: "?").first ?? rawPath

            guard method == "GET" else {
                self.sendJSON(connection, status: "405 Method Not Allowed", payload: ["ok": false, "error": "method not allowed"])
                return
            }

            switch path {
            case "/", "/index.html":
                self.sendHTML(connection)
            case "/health":
                self.sendJSON(connection, status: "200 OK", payload: ["ok": true, "service": "lisbon-camera-bridge"])
            case "/status":
                self.sendJSON(connection, status: "200 OK", payload: self.store.status(mode: self.mode, port: self.port))
            case "/frame.jpg", "/latest.jpg":
                self.sendFrame(connection)
            case "/stream.mjpeg":
                self.sendMJPEGStream(connection)
            default:
                self.sendJSON(connection, status: "404 Not Found", payload: ["ok": false, "error": "not found"])
            }
        }
    }

    private func sendHTML(_ connection: NWConnection) {
        let html = """
        <!doctype html>
        <html>
          <head>
            <title>Lisbon Camera Bridge</title>
            <base href="./" />
          </head>
          <body style="margin:0;background:#111;color:#eee;font-family:-apple-system,BlinkMacSystemFont,sans-serif">
            <div style="padding:12px">Lisbon Camera Bridge — <a style="color:#8cf" href="status">status</a></div>
            <img src="stream.mjpeg" style="width:100vw;height:auto;display:block" />
          </body>
        </html>
        """
        send(connection,
             status: "200 OK",
             headers: ["Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"],
             body: Data(html.utf8))
    }

    private func sendJSON(_ connection: NWConnection, status: String, payload: [String: Any]) {
        send(connection,
             status: status,
             headers: ["Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"],
             body: jsonData(payload))
    }

    private func sendFrame(_ connection: NWConnection) {
        guard let frame = store.snapshot() else {
            sendJSON(connection, status: "503 Service Unavailable", payload: ["ok": false, "error": "no frame available yet"])
            return
        }
        send(connection,
             status: "200 OK",
             headers: [
                "Content-Type": "image/jpeg",
                "Cache-Control": "no-store",
                "X-Frame-Count": String(frame.frameCount),
                "X-Frame-Width": String(frame.width),
                "X-Frame-Height": String(frame.height)
             ],
             body: frame.jpeg)
    }

    private func send(_ connection: NWConnection, status: String, headers: [String: String], body: Data) {
        var response = Data()
        response.appendString("HTTP/1.1 \(status)\r\n")
        response.appendString("Content-Length: \(body.count)\r\n")
        response.appendString("Connection: close\r\n")
        for (key, value) in headers.sorted(by: { $0.key < $1.key }) {
            response.appendString("\(key): \(value)\r\n")
        }
        response.appendString("\r\n")
        response.append(body)
        connection.send(content: response, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private func sendMJPEGStream(_ connection: NWConnection) {
        let header = """
        HTTP/1.1 200 OK\r
        Content-Type: multipart/x-mixed-replace; boundary=lisbonframe\r
        Cache-Control: no-store\r
        Connection: close\r
        \r

        """
        connection.send(content: Data(header.utf8), completion: .contentProcessed { [weak self] error in
            guard error == nil else {
                connection.cancel()
                return
            }
            self?.sendNextMJPEGFrame(connection)
        })
    }

    private func sendNextMJPEGFrame(_ connection: NWConnection) {
        queue.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            guard let self else { return }
            guard let frame = self.store.snapshot() else {
                self.sendNextMJPEGFrame(connection)
                return
            }

            var part = Data()
            part.appendString("--lisbonframe\r\n")
            part.appendString("Content-Type: image/jpeg\r\n")
            part.appendString("Content-Length: \(frame.jpeg.count)\r\n")
            part.appendString("X-Frame-Count: \(frame.frameCount)\r\n")
            part.appendString("\r\n")
            part.append(frame.jpeg)
            part.appendString("\r\n")

            connection.send(content: part, completion: .contentProcessed { [weak self] error in
                if error != nil {
                    connection.cancel()
                    return
                }
                self?.sendNextMJPEGFrame(connection)
            })
        }
    }
}

let config = parseConfig()
let mode = config.mock ? "mock" : "camera"
let store = FrameStore()

var retained: [AnyObject] = []

do {
    let server = try HTTPServer(store: store, mode: mode, port: config.port)
    server.start()
    retained.append(server)

    let writer = SnapshotWriter(store: store, path: config.snapshotPath, interval: config.snapshotInterval)
    writer.start()
    retained.append(writer)

    if config.mock {
        let source = MockFrameSource(store: store, fps: config.fps)
        source.start()
        retained.append(source)
    } else {
        let capture = CameraCapture(store: store, fps: config.fps)
        capture.startWhenAuthorized()
        retained.append(capture)
    }

    log("Lisbon camera bridge running in \(mode) mode; endpoints: /health /status /frame.jpg /stream.mjpeg")
    RunLoop.main.run()
} catch {
    fputs("Failed to start Lisbon camera bridge: \(error)\n", stderr)
    exit(1)
}
