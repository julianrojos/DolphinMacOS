import AppKit
import UniformTypeIdentifiers

struct App: Codable {
    let bundleID: String
    let name: String
    let path: String
}
struct Result: Codable {
    let contentType: String
    let applications: [App]
    let defaultBundleID: String?
}
let workspace = NSWorkspace.shared
var results: [String: Result] = [:]
for ext in CommandLine.arguments.dropFirst() {
    guard let type = UTType(filenameExtension: ext) else { continue }
    // Return every copy: the caller filters by location before keeping one
    // per bundle id, so an excluded first copy cannot hide a valid one.
    let apps = workspace.urlsForApplications(toOpen: type).compactMap { url -> App? in
        guard let bundle = Bundle(url: url), let id = bundle.bundleIdentifier else { return nil }
        let name = FileManager.default.displayName(atPath: url.path)
        return App(bundleID: id, name: name, path: url.path)
    }
    let defaultID = workspace.urlForApplication(toOpen: type).flatMap { Bundle(url: $0)?.bundleIdentifier }
    results[ext] = Result(contentType: type.identifier, applications: apps, defaultBundleID: defaultID)
}
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
FileHandle.standardOutput.write(try encoder.encode(results))
