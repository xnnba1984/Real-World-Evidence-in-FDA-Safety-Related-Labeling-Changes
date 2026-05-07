# Annotation User Prompt Template v2

Each rendered prompt contains:
- event metadata
- full `change_text`
- a non-binding heuristic summary from the local rule layer
- selected document metadata
- selected evidence snippets

The heuristic section is included to guide attention, but the model is instructed to treat it as fallible.
The final annotation must be grounded in the packet evidence rather than in the heuristic itself.
