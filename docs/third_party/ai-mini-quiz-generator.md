# AI Mini-Quiz Generator Attribution

The assessment structured-generation workflow is adapted from the
`QuizQuestion` / `FullQuiz` schemas and `generate_quiz` function in `utils.py`:

- Repository: https://github.com/meleknurb/ai-mini-quiz-generator
- Audited commit: `86db2ffd80d99d8db41b3b4f85d00129a23f80be`
- Source: https://github.com/meleknurb/ai-mini-quiz-generator/blob/86db2ffd80d99d8db41b3b4f85d00129a23f80be/utils.py
- License: MIT (permission notice reproduced below)

Local adaptations use the existing model factory and textbook retriever,
Chinese question instructions, bounded evidence, stable answer option IDs,
and executable output constraints. Streamlit, PDF ingestion, Gemini-specific
clients, and coaching-report generation are not imported. This is a source
adaptation, not a runtime dependency or an unmodified upstream engine.

## License

Copyright 2026 Melek Nur

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
