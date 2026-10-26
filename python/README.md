# visset

Step-by-step visual explanations of code. visset runs a Python program, records every step with
the exact expression involved, and plays it back as a guided walkthrough: the code with a
hand-drawn mark on what just ran, the call stack and variables beside it, and a plain-English
caption.

```bash
visset run bsearch.py                      # trace and open in the browser
visset run bsearch.py -o bsearch.html      # one self-contained HTML file
visset run bsearch.py --fn binary_search --args "[1, 3, 5, 7], 5"
```

```python
import visset

trace = visset.trace(source, function="binary_search", args=([1, 3, 5, 7], 5))
visset.show(trace)          # like plt.show()
```

- Python 3.12+ (uses `sys.monitoring`), no runtime dependencies.
- Programs run in a child process with time, memory and step limits. This protects against
  accidents, not malicious code.

Documentation, the trace schema and the roadmap: https://github.com/nur0078/visset
