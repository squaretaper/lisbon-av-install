// set_output.swift — set the macOS default audio output device by name (offline, no deps).
// Build:  swiftc set_output.swift -o set_output -framework CoreAudio -framework Foundation
// List :  ./set_output --list
// Set  :  ./set_output ES-9      (matches by substring; picks an output-capable device)
import CoreAudio
import Foundation

func allDevices() -> [AudioDeviceID] {
    var size: UInt32 = 0
    var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
                                       mScope: kAudioObjectPropertyScopeGlobal,
                                       mElement: kAudioObjectPropertyElementMain)
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size)
    let n = Int(size) / MemoryLayout<AudioDeviceID>.size
    var ids = [AudioDeviceID](repeating: 0, count: n)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size, &ids)
    return ids
}
func deviceName(_ id: AudioDeviceID) -> String {
    var a = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
                                       mScope: kAudioObjectPropertyScopeGlobal,
                                       mElement: kAudioObjectPropertyElementMain)
    var name: Unmanaged<CFString>?
    var sz = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    AudioObjectGetPropertyData(id, &a, 0, nil, &sz, &name)
    return (name?.takeRetainedValue() as String?) ?? ""
}
func outputChannels(_ id: AudioDeviceID) -> Int {
    var a = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
                                       mScope: kAudioObjectPropertyScopeOutput,
                                       mElement: kAudioObjectPropertyElementMain)
    var sz: UInt32 = 0
    AudioObjectGetPropertyDataSize(id, &a, 0, nil, &sz)
    if sz == 0 { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(sz), alignment: 16)
    defer { raw.deallocate() }
    AudioObjectGetPropertyData(id, &a, 0, nil, &sz, raw)
    let abl = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    var ch = 0
    for b in abl { ch += Int(b.mNumberChannels) }
    return ch
}
func setDefaultOutput(_ id: AudioDeviceID) {
    var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice,
                                       mScope: kAudioObjectPropertyScopeGlobal,
                                       mElement: kAudioObjectPropertyElementMain)
    var dev = id
    let st = AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil,
                                        UInt32(MemoryLayout<AudioDeviceID>.size), &dev)
    if st != noErr { FileHandle.standardError.write("set failed: \(st)\n".data(using: .utf8)!); exit(2) }
}

let outs = allDevices().filter { outputChannels($0) > 0 }
let args = CommandLine.arguments
if args.count < 2 || args[1] == "--list" {
    for d in outs { print("\(deviceName(d))  (out ch: \(outputChannels(d)))") }
} else {
    let q = args[1]
    if let d = outs.first(where: { deviceName($0).localizedCaseInsensitiveContains(q) }) {
        setDefaultOutput(d)
        print("default output -> \(deviceName(d))")
    } else {
        FileHandle.standardError.write("no output device matching '\(q)'\n".data(using: .utf8)!); exit(1)
    }
}
