import Foundation
// swift-tools-version: 6.0
import PackageDescription

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().path
let package = Package(
  name: "AppleDeskCalendar", platforms: [.macOS(.v14)],
  products: [.executable(name: "apple-desk-calendar", targets: ["CalendarHelper"])],
  targets: [
    .target(name: "CalendarCore"),
    .executableTarget(
      name: "CalendarHelper", dependencies: ["CalendarCore"],
      linkerSettings: [
        .unsafeFlags([
          "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist", "-Xlinker",
          root + "/Info.plist",
        ])
      ]),
    .testTarget(name: "CalendarCoreTests", dependencies: ["CalendarCore"]),
  ], swiftLanguageModes: [.v5])
