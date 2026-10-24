"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const ts = require("typescript");
module.exports = function load(relative, imports, globals = {}) {
  const filename = path.resolve(__dirname, "..", relative);
  const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true}
  }).outputText;
  const exports = {};
  const context = vm.createContext({exports, URL, ...globals, require(name) {
    if (Object.hasOwn(imports, name)) return imports[name];
    if (name.endsWith(".json")) return JSON.parse(fs.readFileSync(path.resolve(path.dirname(filename), name), "utf8"));
    throw new Error("Unmocked module: " + name);
  }});
  vm.runInContext(code, context, {filename});
  return exports;
};
