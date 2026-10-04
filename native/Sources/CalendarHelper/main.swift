import CalendarCore
import Foundation

func output(_ value: [String: Any], code: Int32) -> Never {
  do {
    let data = try JSONSerialization.data(
      withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
  } catch {
    FileHandle.standardOutput.write(
      Data(
        "{\"ok\":false,\"error\":{\"code\":\"ENCODING_ERROR\",\"message\":\"Native calendar response could not be encoded.\"}}\n"
          .utf8))
    exit(1)
  }
  exit(code)
}
func readRequest(_ handle: FileHandle) -> Data {
  var result = Data()
  while result.count <= 1_048_576 {
    let chunk = handle.readData(ofLength: min(65_536, 1_048_577 - result.count))
    if chunk.isEmpty { break }
    result.append(chunk)
  }
  return result
}
do {
  let args = Array(CommandLine.arguments.dropFirst())
  let bytes: Data
  if args.count == 2 && args[0] == "--request" {
    let file = try FileHandle(forReadingFrom: URL(fileURLWithPath: args[1]))
    defer { try? file.close() }
    bytes = readRequest(file)
  } else if args.isEmpty {
    bytes = readRequest(FileHandle.standardInput)
  } else {
    throw CalendarError("INVALID_INPUT", "Pass JSON on stdin, or --request FILE.")
  }
  guard bytes.count <= 1_048_576 else {
    throw CalendarError("INVALID_INPUT", "Expected a JSON object of at most 1 MiB.")
  }
  guard let request = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] else {
    throw CalendarError("INVALID_INPUT", "Expected a valid JSON object.")
  }
  output(["ok": true, "data": try CalendarService().run(request)], code: 0)
} catch let error as CalendarError {
  output(
    [
      "ok": false,
      "error": ["code": error.code, "message": error.message, "details": error.details ?? [:]],
    ], code: error.code == "PERMISSION_REQUIRED" ? 3 : 2)
} catch {
  output(
    ["ok": false, "error": ["code": "NATIVE_ERROR", "message": error.localizedDescription]], code: 1
  )
}
