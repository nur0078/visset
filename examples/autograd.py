# A tiny autograd engine in the style of micrograd: each Value remembers the
# Values it was made from (_prev), so backward() can walk the graph.
# micrograd keeps _prev in a set; a tuple keeps this example's trace the same on every run,
# and relu (not tanh, whose last digit varies by platform) keeps the numbers exact.


class Value:
    def __init__(self, data, _children=(), _op="", label=""):
        self.data = data
        self.grad = 0.0
        self._backward = lambda: None
        self._prev = tuple(_children)
        self._op = _op
        self.label = label

    def __add__(self, other):
        out = Value(self.data + other.data, (self, other), "+")

        def _backward():
            self.grad += out.grad
            other.grad += out.grad

        out._backward = _backward
        return out

    def __mul__(self, other):
        out = Value(self.data * other.data, (self, other), "*")

        def _backward():
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad

        out._backward = _backward
        return out

    def relu(self):
        out = Value(max(0.0, self.data), (self,), "relu")

        def _backward():
            self.grad += (out.data > 0) * out.grad

        out._backward = _backward
        return out

    def backward(self):
        topo = []
        visited = set()

        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)

        build_topo(self)
        self.grad = 1.0
        for node in reversed(topo):
            node._backward()


x = Value(2.0, label="x")
w = Value(-3.0, label="w")
b = Value(6.88, label="b")
n = x * w + b
n.label = "n"
o = n.relu()
o.label = "o"
o.backward()
print(round(x.grad, 4), round(w.grad, 4))
