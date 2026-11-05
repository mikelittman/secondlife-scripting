(function_definition
  body: (compound_statement) @function.inside) @function.around

(event_handler
  body: (compound_statement) @function.inside) @function.around

(state_definition) @class.around

(comment) @comment.around
