# visset

Step-by-step visual explanations of code. visset runs a Python program, records every step with
the exact expression involved, and plays it back as a guided walkthrough: the code with a
hand-drawn mark on what just ran, the call stack and variables beside it, and a plain-English
caption.

visset is made for a function, a snippet, or part of a function, not a whole codebase.

```python
import visset

visset.show(binary_search, [1, 3, 5, 7], 5)                      # one call, like plt.show()
visset.show("total = 0\nfor x in xs:\n    total += x", given={"xs": [4, 5]})
```

```bash
visset run bsearch.py --fn binary_search --args "[1, 3, 5, 7], 5"
visset run bsearch.py --lines 4-9 -o part.html      # just part of it, as one HTML file
```

- Python 3.12+ (uses `sys.monitoring`), no runtime dependencies.
- Programs run in a child process with time, memory and step limits. This protects against
  accidents, not malicious code.

Documentation, the trace schema and the roadmap: https://github.com/nur0078/visset
