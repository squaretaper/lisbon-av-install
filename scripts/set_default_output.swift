// Set default macOS audio output device by name match.
// Usage: swift set_default_output.swift "ES-9"
// Native CoreAudio — no external deps.

import Foundation
import CoreAudio

func deviceList() -> [AudioDeviceID] {
    var size: UInt32 = 0
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
    let count = Int(size) / MemoryLayout<AudioDeviceID>.size
    var ids = [AudioDeviceID](repeating: 0, count: count)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
    return ids
}

func deviceName(_ id: AudioDeviceID) -> String {
    var name: CFString = "" as CFString
    var size = UInt32(MemoryLayout<CFString>.size)
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioObjectPropertyName,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &name)
    return name as String
}

func hasOutput(_ id: AudioDeviceID) -> Bool {
    var size: UInt32 = 0
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyStreams,
        mScope: kAudioDevicePropertyScopeOutput,
        mElement: kAudioObjectPropertyElementMain)
    AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size)
    return size > 0
}

guard CommandLine.arguments.count > 1 else {
    print("usage: swift set_default_output.swift <device-name-substring>")
    exit(2)
}
let target = CommandLine.arguments[1].lowercased()

let candidates = deviceList().filter(hasOutput)
guard let match = candidates.first(where: { deviceName($0).lowercased().contains(target) }) else {
    print("no output device matching '\(target)'. available:")
    for id in candidates { print("  - \(deviceName(id))") }
    exit(1)
}

var dev = match
var addr = AudioObjectPropertyAddress(
    mSelector: kAudioHardwarePropertyDefaultOutputDevice,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
let status = AudioObjectSetPropertyData(
    AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil,
    UInt32(MemoryLayout<AudioDeviceID>.size), &dev)

if status == noErr {
    print("default output -> \(deviceName(match))")
} else {
    print("failed: OSStatus \(status)")
    exit(1)
}
