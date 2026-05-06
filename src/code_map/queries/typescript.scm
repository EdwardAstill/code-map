;; Symbols: function declarations (including exported), class declarations,
;; method definitions inside class bodies, and exported lexical constants.
;; Imports captured separately for edge derivation.
;;
;; Derived from aider (https://github.com/Aider-AI/aider) under Apache-2.0.
;; See ATTRIBUTION.md for provenance.

(function_declaration name: (identifier) @symbol.function)

(class_declaration name: (type_identifier) @symbol.class
  body: (class_body (method_definition name: (property_identifier) @symbol.method)))

(class_declaration name: (type_identifier) @symbol.class)

(interface_declaration name: (type_identifier) @symbol.class)

(method_definition name: (property_identifier) @symbol.method)

(export_statement
  (lexical_declaration
    (variable_declarator name: (identifier) @symbol.constant)))

(import_statement source: (string) @import.module)

(import_statement
  (import_clause (named_imports (import_specifier name: (identifier) @import.name)))
  source: (string) @import.module)

(call_expression function: (identifier) @call.callee)

(call_expression function: (member_expression
  object: (identifier) @call.receiver
  property: (property_identifier) @call.method))
