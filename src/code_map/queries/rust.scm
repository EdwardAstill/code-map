;; Symbols: functions, structs, enums, traits, impl methods, constants.
;; Edges: use declarations (imports), direct calls, scoped calls, field-expression calls.

(function_item name: (identifier) @symbol.function)
(struct_item name: (type_identifier) @symbol.type)
(enum_item name: (type_identifier) @symbol.type)
(trait_item name: (type_identifier) @symbol.type)
(impl_item body: (declaration_list (function_item name: (identifier) @symbol.method)))
(const_item name: (identifier) @symbol.constant)

(use_declaration argument: (scoped_identifier) @use.path)

(call_expression function: (identifier) @call.callee)
(call_expression function: (scoped_identifier
  path: (identifier) @call.receiver
  name: (identifier) @call.method))
(call_expression function: (field_expression
  field: (field_identifier) @call.method))
