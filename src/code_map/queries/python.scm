;; Symbols: function and class definitions, method bodies inside class blocks,
;; module-level constants. Imports captured separately for edge derivation.
;;
;; Derived from aider (https://github.com/Aider-AI/aider) under Apache-2.0.
;; See ATTRIBUTION.md for provenance.

(function_definition name: (identifier) @symbol.function)

(class_definition name: (identifier) @symbol.class
  body: (block (function_definition name: (identifier) @symbol.method)))

(class_definition name: (identifier) @symbol.class)

(module
  (expression_statement
    (assignment left: (identifier) @symbol.constant)))

(import_statement (dotted_name) @import.module)

(import_from_statement
  module_name: (dotted_name) @import.from.module
  name: (dotted_name) @import.from.name)

(import_from_statement
  module_name: (dotted_name) @import.from.module
  name: (aliased_import name: (dotted_name) @import.from.name))

(call function: (identifier) @call.callee)

(call function: (attribute object: (identifier) @call.receiver attribute: (identifier) @call.method))
