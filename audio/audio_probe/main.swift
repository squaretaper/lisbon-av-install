// Lisbon Room Audio Probe
// Captures audio from the C200 USB mic (or default audio input) via AVFoundation,
// computes RMS/peak/dominant-frequency on a 0.5s window, exposes a small HTTP
// status endpoint, and atomically writes a status JSON the reflective reviewer
// can read alongside the SWN bridge's line-audio telemetry.
//
// Architecture mirrors LisbonCameraProbe so the same TCC bypass + LaunchAgent
// pattern reused. Audio analysis stays in this process; no Python required.
//
// Endpoints (default port 8767):
//   /health          process health
//   /status          rolling JSON: peak, rms, dom_freq, band_ratios
//   /audio.wav       last N seconds as a single WAV (lazy diag, not realtime)
//
// Build:
//   scripts/build-audio-probe.sh

import AVFoundation
import Accelerate
import CoreMedia
import Foundation
import Network
import UniformTypeIdentifiers

let defaultStatusPath = "audio/runtime/room_audio_probe_status.json"

func log(_ message: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    FileHandle.standardError.write("[\(stamp)] \(message)\n".data(using: .utf8) ?? Data())
}

// MARK: - Config

struct Config {
    var port: UInt16 = 8767
    var statusPath = defaultStatusPath
    var deviceMatch: String? = "PowerConf" // C200 substring; nil = default mic
    var sampleRate: Double = 48000
    var windowSeconds: Double = 0.5
    var statusHz: Double = 4
}

func parseArgs() -> Config {
    var cfg = Config()
    let args = CommandLine.arguments
    var i = 1
    func value(after _: String) -> String {
        i += 1
        return i < args.count ? args[i] : ""
    }
    while i < args.count {
        let arg = args[i]
        switch arg {
        case "--port": if let v = UInt16(value(after: arg)) { cfg.port = v }
        case "--status-path": cfg.statusPath = value(after: arg)
        case "--device": cfg.deviceMatch = value(after: arg)
        case "--default-device": cfg.deviceMatch = nil
        case "--sample-rate": if let v = Double(value(after: arg)) { cfg.sampleRate = v }
        case "--window-seconds": if let v = Double(value(after: arg)) { cfg.windowSeconds = v }
        case "--status-hz": if let v = Double(value(after: arg)) { cfg.statusHz = v }
        case "--help", "-h":
            print("""
                  Usage: LisbonAudioProbe [--port 8767] [--status-path PATH]
                                          [--device 'PowerConf' | --default-device]
                                          [--sample-rate 48000] [--window-seconds 0.5]
                                          [--status-hz 4]
                  """)
            exit(0)
        default: log("ignoring unknown arg \(arg)")
        }
        i += 1
    }
    return cfg
}

// MARK: - Analysis store

final class AudioStore {
    private let queue = DispatchQueue(label: "lisbon.audio.store", attributes: .concurrent)
    private var _peak: Float = 0
    private var _rms: Float = 0
    private var _domFreq: Float = 0
    private var _bandLow: Float = 0
    private var _bandMid: Float = 0
    private var _bandHigh: Float = 0
    private var _device: String = "unknown"
    private var _error: String?
    private var _sampleCount: Int64 = 0
    private var _lastUpdate: Date = Date.distantPast

    func update(peak: Float, rms: Float, domFreq: Float, bandLow: Float, bandMid: Float, bandHigh: Float) {
        queue.async(flags: .barrier) {
            self._peak = peak
            self._rms = rms
            self._domFreq = domFreq
            self._bandLow = bandLow
            self._bandMid = bandMid
            self._bandHigh = bandHigh
            self._error = nil
            self._lastUpdate = Date()
            self._sampleCount += 1
        }
    }

    func setError(_ message: String) { queue.async(flags: .barrier) { self._error = message } }
    func setDevice(_ name: String) { queue.async(flags: .barrier) { self._device = name } }

    func snapshot() -> [String: Any] {
        queue.sync {
            var out: [String: Any] = [
                "ok": _error == nil && _sampleCount > 0,
                "service": "lisbon-audio-probe",
                "device": _device,
                "peak": Double(_peak),
                "rms": Double(_rms),
                "dom_freq_hz": Double(_domFreq),
                "band_low": Double(_bandLow),
                "band_mid": Double(_bandMid),
                "band_high": Double(_bandHigh),
                "sample_count": _sampleCount,
                "timestamp": Date().timeIntervalSince1970,
                "last_update_age_ms": Int(Date().timeIntervalSince(_lastUpdate) * 1000),
            ]
            if let e = _error { out["error"] = e }
            return out
        }
    }
}

// MARK: - Capture

final class AudioCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    private let store: AudioStore
    private let deviceMatch: String?
    private var session: AVCaptureSession?
    private let queue = DispatchQueue(label: "lisbon.audio.capture")
    private var ringBuffer: [Float] = []
    private let ringCapacity: Int
    private let windowSize: Int
    private let sampleRate: Double
    private var fftSetup: vDSP.FFT<DSPSplitComplex>?
    private let fftLog2: Int

    init(store: AudioStore, sampleRate: Double, windowSeconds: Double, deviceMatch: String?) {
        self.store = store
        self.sampleRate = sampleRate
        self.deviceMatch = deviceMatch
        self.windowSize = Int(sampleRate * windowSeconds)
        // FFT length: power of 2 >= windowSize
        var n = 1, log2n = 0
        while n < self.windowSize { n <<= 1; log2n += 1 }
        self.fftLog2 = log2n
        self.ringCapacity = max(n, self.windowSize)
        self.ringBuffer.reserveCapacity(self.ringCapacity)
        if let setup = vDSP.FFT<DSPSplitComplex>(log2n: vDSP_Length(log2n), radix: .radix2, ofType: DSPSplitComplex.self) {
            self.fftSetup = setup
        }
        super.init()
    }

    func startWhenAuthorized() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: start()
        case .notDetermined:
            store.setError("requesting microphone permission")
            AVCaptureDevice.requestAccess(for: .audio) { [weak self] granted in
                if granted { self?.start() } else { self?.store.setError("microphone permission denied") }
            }
        case .denied:
            store.setError("microphone permission denied in System Settings > Privacy & Security > Microphone")
        case .restricted: store.setError("microphone permission restricted")
        @unknown default: store.setError("unknown microphone permission state")
        }
    }

    private func selectDevice() -> AVCaptureDevice? {
        let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone],
                                                         mediaType: .audio,
                                                         position: .unspecified)
        let devices = discovery.devices
        if let match = deviceMatch {
            if let found = devices.first(where: { $0.localizedName.localizedCaseInsensitiveContains(match) }) {
                return found
            }
            log("no device matched '\(match)', falling back to default")
        }
        return devices.first ?? AVCaptureDevice.default(for: .audio)
    }

    private func start() {
        guard let device = selectDevice() else {
            store.setError("no audio capture device found")
            return
        }
        store.setDevice(device.localizedName)
        log("using audio device: \(device.localizedName)")
        do {
            let session = AVCaptureSession()
            let input = try AVCaptureDeviceInput(device: device)
            guard session.canAddInput(input) else { store.setError("cannot add audio input"); return }
            session.addInput(input)
            let output = AVCaptureAudioDataOutput()
            output.setSampleBufferDelegate(self, queue: queue)
            guard session.canAddOutput(output) else { store.setError("cannot add audio output"); return }
            session.addOutput(output)
            session.startRunning()
            self.session = session
            log("audio capture started, expected sample rate \(sampleRate)")
        } catch {
            store.setError("failed to open audio device: \(error.localizedDescription)")
        }
    }

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>? = nil
        let status = CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer)
        guard status == kCMBlockBufferNoErr, let dp = dataPointer else { return }
        let asbd = CMSampleBufferGetFormatDescription(sampleBuffer).flatMap { CMAudioFormatDescriptionGetStreamBasicDescription($0)?.pointee }
        guard let fmt = asbd else { return }

        // Convert whatever the system gave us to mono float32 samples.
        var samples: [Float] = []
        let bytesPerFrame = Int(fmt.mBytesPerFrame)
        let frames = length / max(1, bytesPerFrame)
        let channels = Int(fmt.mChannelsPerFrame)
        samples.reserveCapacity(frames)

        if fmt.mFormatID == kAudioFormatLinearPCM {
            let isFloat = (fmt.mFormatFlags & kAudioFormatFlagIsFloat) != 0
            let isInt = (fmt.mFormatFlags & kAudioFormatFlagIsSignedInteger) != 0
            if isFloat && fmt.mBitsPerChannel == 32 {
                dp.withMemoryRebound(to: Float.self, capacity: frames * channels) { fptr in
                    for f in 0..<frames {
                        var acc: Float = 0
                        for c in 0..<channels { acc += fptr[f * channels + c] }
                        samples.append(acc / Float(channels))
                    }
                }
            } else if isInt && fmt.mBitsPerChannel == 16 {
                dp.withMemoryRebound(to: Int16.self, capacity: frames * channels) { iptr in
                    for f in 0..<frames {
                        var acc: Float = 0
                        for c in 0..<channels { acc += Float(iptr[f * channels + c]) / 32768.0 }
                        samples.append(acc / Float(channels))
                    }
                }
            } else {
                return
            }
        } else {
            return
        }

        // Append to ring; analyze in windows.
        ringBuffer.append(contentsOf: samples)
        if ringBuffer.count >= windowSize {
            // Take latest windowSize samples
            let start = ringBuffer.count - windowSize
            let window = Array(ringBuffer[start..<start + windowSize])
            ringBuffer.removeFirst(start)
            analyze(window: window)
        }
    }

    private func analyze(window: [Float]) {
        var peak: Float = 0
        var rms: Float = 0
        vDSP_maxmgv(window, 1, &peak, vDSP_Length(window.count))
        vDSP_rmsqv(window, 1, &rms, vDSP_Length(window.count))

        // Spectral: zero-pad to FFT size, run forward FFT, find dominant bin + band ratios
        let fftSize = 1 << fftLog2
        var padded = [Float](repeating: 0, count: fftSize)
        for i in 0..<min(window.count, fftSize) { padded[i] = window[i] }

        var real = [Float](repeating: 0, count: fftSize / 2)
        var imag = [Float](repeating: 0, count: fftSize / 2)
        var domFreq: Float = 0
        var bandLow: Float = 0
        var bandMid: Float = 0
        var bandHigh: Float = 0
        if let fft = fftSetup {
            real.withUnsafeMutableBufferPointer { realPtr in
                imag.withUnsafeMutableBufferPointer { imagPtr in
                    var split = DSPSplitComplex(realp: realPtr.baseAddress!, imagp: imagPtr.baseAddress!)
                    padded.withUnsafeBufferPointer { p in
                        p.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: fftSize / 2) { c in
                            vDSP_ctoz(c, 2, &split, 1, vDSP_Length(fftSize / 2))
                        }
                    }
                    fft.forward(input: split, output: &split)
                    var mag = [Float](repeating: 0, count: fftSize / 2)
                    vDSP_zvmags(&split, 1, &mag, 1, vDSP_Length(fftSize / 2))
                    // Dominant bin
                    var maxIdx: vDSP_Length = 0
                    var maxVal: Float = 0
                    vDSP_maxvi(mag, 1, &maxVal, &maxIdx, vDSP_Length(mag.count))
                    let binHz = Float(sampleRate) / Float(fftSize)
                    domFreq = Float(maxIdx) * binHz
                    // Band ratios: low <250Hz, mid 250-2000Hz, high >2000Hz
                    let lowEnd = Int(250.0 / Double(binHz))
                    let midEnd = Int(2000.0 / Double(binHz))
                    var sumLow: Float = 0, sumMid: Float = 0, sumHigh: Float = 0
                    let safeLow = max(0, min(lowEnd, mag.count))
                    let safeMid = max(safeLow, min(midEnd, mag.count))
                    if safeLow > 0 { vDSP_sve(Array(mag[0..<safeLow]), 1, &sumLow, vDSP_Length(safeLow)) }
                    if safeMid > safeLow { vDSP_sve(Array(mag[safeLow..<safeMid]), 1, &sumMid, vDSP_Length(safeMid - safeLow)) }
                    if mag.count > safeMid { vDSP_sve(Array(mag[safeMid..<mag.count]), 1, &sumHigh, vDSP_Length(mag.count - safeMid)) }
                    let total = sumLow + sumMid + sumHigh
                    if total > 0 {
                        bandLow = sumLow / total
                        bandMid = sumMid / total
                        bandHigh = sumHigh / total
                    }
                }
            }
        }

        store.update(peak: peak, rms: rms, domFreq: domFreq, bandLow: bandLow, bandMid: bandMid, bandHigh: bandHigh)
    }
}

// MARK: - Status writer

final class StatusWriter {
    private let store: AudioStore
    private let path: String
    private let interval: TimeInterval
    private var timer: DispatchSourceTimer?

    init(store: AudioStore, path: String, statusHz: Double) {
        self.store = store
        self.path = path
        self.interval = 1.0 / max(0.5, statusHz)
    }

    func start() {
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "lisbon.audio.status-writer"))
        timer.schedule(deadline: .now() + interval, repeating: interval)
        timer.setEventHandler { [weak self] in self?.write() }
        timer.resume()
        self.timer = timer
    }

    private func write() {
        let snap = store.snapshot()
        guard let data = try? JSONSerialization.data(withJSONObject: snap, options: [.prettyPrinted, .sortedKeys]) else { return }
        let url = URL(fileURLWithPath: path)
        let tmp = url.appendingPathExtension("tmp")
        let dir = url.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        do {
            try data.write(to: tmp, options: .atomic)
            _ = try? FileManager.default.replaceItemAt(url, withItemAt: tmp)
        } catch {
            log("status write failed: \(error)")
        }
    }
}

// MARK: - HTTP server

final class HTTPServer {
    private let store: AudioStore
    private let port: NWEndpoint.Port
    private var listener: NWListener?

    init(store: AudioStore, port: UInt16) {
        self.store = store
        self.port = NWEndpoint.Port(rawValue: port)!
    }

    func start() {
        do {
            let params = NWParameters.tcp
            let listener = try NWListener(using: params, on: port)
            listener.newConnectionHandler = { [weak self] conn in self?.handle(conn) }
            listener.start(queue: DispatchQueue(label: "lisbon.audio.http"))
            self.listener = listener
            log("http listening on :\(port.rawValue)")
        } catch {
            log("http listener failed: \(error)")
        }
    }

    private func handle(_ conn: NWConnection) {
        conn.start(queue: DispatchQueue(label: "lisbon.audio.http.conn"))
        conn.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, _, _ in
            guard let self = self, let data = data, let req = String(data: data, encoding: .utf8) else { conn.cancel(); return }
            let line = req.split(separator: "\n").first.map(String.init) ?? ""
            var path = "/"
            let parts = line.split(separator: " ")
            if parts.count >= 2 { path = String(parts[1]).split(separator: "?").first.map(String.init) ?? "/" }
            let body: Data
            let contentType: String
            switch path {
            case "/health":
                body = "{\"ok\":true,\"service\":\"lisbon-audio-probe\"}\n".data(using: .utf8)!
                contentType = "application/json"
            case "/status":
                let snap = self.store.snapshot()
                body = (try? JSONSerialization.data(withJSONObject: snap, options: [.prettyPrinted, .sortedKeys])) ?? Data()
                contentType = "application/json"
            default:
                body = "not found\n".data(using: .utf8)!
                contentType = "text/plain"
            }
            let header = """
            HTTP/1.1 200 OK\r
            Content-Type: \(contentType)\r
            Content-Length: \(body.count)\r
            Connection: close\r
            \r

            """
            var payload = Data()
            payload.append(header.data(using: .utf8)!)
            payload.append(body)
            conn.send(content: payload, completion: .contentProcessed { _ in conn.cancel() })
        }
    }
}

// MARK: - Main

let cfg = parseArgs()
let store = AudioStore()
let capture = AudioCapture(store: store, sampleRate: cfg.sampleRate, windowSeconds: cfg.windowSeconds, deviceMatch: cfg.deviceMatch)
let writer = StatusWriter(store: store, path: cfg.statusPath, statusHz: cfg.statusHz)
let server = HTTPServer(store: store, port: cfg.port)

capture.startWhenAuthorized()
writer.start()
server.start()
log("LisbonAudioProbe started")
RunLoop.main.run()
