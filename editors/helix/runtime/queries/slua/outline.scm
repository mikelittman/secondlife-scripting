(function_declaration
  name: (identifier) @name) @item

(function_declaration
  name: (dot_index_expression
    field: (identifier) @name)) @item

(function_definition
  name: (identifier) @name) @item

(type_definition
  (type) @name) @item
