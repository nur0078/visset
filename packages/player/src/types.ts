// Mirrors schema/trace.schema.json. The player relies only on these shapes: no language knowledge.

/** [line, column]: 1-based line, 0-based column counted in Unicode code points. */
export type Pos = [line: number, col: number];

export type Value = { p: string; t: string } | { ref: string };

export type Shape = 'sequence' | 'mapping' | 'set' | 'record' | 'function' | 'class' | 'opaque';

export interface HeapObject {
  type: string;
  shape: Shape;
  items?: Value[];
  entries?: [Value, Value][];
  fields?: [string, Value][];
  repr?: string;
  more?: number;
}

export type MarkKind =
  | 'circle'
  | 'underline'
  | 'box'
  | 'bracket'
  | 'highlight'
  | 'arrow'
  | 'strike';

export interface Mark {
  source: string;
  start: Pos;
  end: Pos;
  mark: MarkKind;
  tone?: 'accent' | 'error';
  label?: string;
}

export interface Frame {
  id: string;
  name: string;
  line?: number;
  locals: [string, Value][];
  returnValue?: Value;
  yieldValue?: Value;
}

export interface Step {
  kind: 'statement' | 'expression' | 'call' | 'return' | 'exception' | 'note';
  focus: Mark[];
  caption?: string;
  captionOrigin?: 'template' | 'author' | 'ai';
  stack: Frame[];
  heap: string[];
  stdout?: string;
  changes?: string[];
  links?: { focus: number; to: string }[];
  hints?: Record<string, string>;
}

export interface Source {
  id: string;
  path?: string;
  text: string;
  tokens?: [line: number, col: number, endCol: number, kind: string][];
}

export interface Trace {
  schema: string;
  meta: {
    language: string;
    runtime?: string;
    generator?: string;
    origin: 'traced' | 'authored' | 'mixed';
    title?: string;
    entry?: string | null;
    truncated?: { reason: string; limit?: number } | null;
    error?: { type: string; message: string; line?: number | null } | null;
  };
  sources: Source[];
  objects: Record<string, HeapObject>;
  steps: Step[];
}
