// On-device category suggester using Apple's Foundation Models (runs entirely on this Mac).
//
// stdin:  one JSON object per line: {"id", "instructions", "prompt", "categories": [ids]}
// stdout: one JSON object per line: {"id", "category"} or {"id", "error"}
// Exit 2 if the on-device model is unavailable.
//
// Uses a runtime schema (DynamicGenerationSchema) instead of @Generable so it builds with the
// Command Line Tools alone (the macros need full Xcode).

import Foundation
import FoundationModels

struct Request: Decodable {
    let id: String
    let instructions: String
    let prompt: String
    let categories: [String]
}

struct Response: Encodable {
    let id: String
    var category: String? = nil
    var error: String? = nil
}

let encoder = JSONEncoder()

func emit(_ response: Response) {
    if let data = try? encoder.encode(response), let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

let model = SystemLanguageModel.default
guard case .available = model.availability else {
    FileHandle.standardError.write("on-device model unavailable: \(model.availability)\n".data(using: .utf8)!)
    exit(2)
}

while let line = readLine(strippingNewline: true) {
    guard !line.isEmpty, let data = line.data(using: .utf8) else { continue }
    guard let request = try? JSONDecoder().decode(Request.self, from: data) else {
        emit(Response(id: "?", error: "bad request"))
        continue
    }
    do {
        let schema = try GenerationSchema(
            root: DynamicGenerationSchema(name: "Classification", properties: [
                .init(name: "category", description: "Category id",
                      schema: DynamicGenerationSchema(name: "Category", anyOf: request.categories)),
            ]),
            dependencies: [])
        let session = LanguageModelSession(instructions: request.instructions)
        let content = try await session.respond(
            to: request.prompt, schema: schema, options: GenerationOptions(sampling: .greedy)).content
        emit(Response(id: request.id, category: try content.value(String.self, forProperty: "category")))
    } catch {
        emit(Response(id: request.id, error: String(describing: error)))
    }
}
