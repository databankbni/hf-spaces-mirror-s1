/*
 * schema-form.js — a dependency-free engine that turns a JSON Schema (2020-12)
 * into an interactive HTML form, reads the form back as a typed JS value, and
 * renders a validation result.
 *
 * It is deliberately validator-agnostic: the caller supplies the validator (the
 * tool-schemas playground passes a @cfworker/json-schema Validator loaded from a
 * CDN, the same library the MCP server validates with) and feeds its output to
 * `renderErrors`. This module never fetches anything and has no build step, so it
 * drops straight into a static page and is reusable by other topic demos.
 *
 * Coverage is pragmatic: it renders the constructs the demo tools actually use —
 * objects, scalar enums (plain, titled oneOf/anyOf-of-const, enumNames), array
 * multi-selects, 2020-12 prefixItems tuples, discriminated unions (oneOf of
 * objects with a const discriminator), and same-document $ref/$defs. Anything it
 * doesn't recognise falls back to a live-validated raw-JSON textarea, so the form
 * is never wrong — at worst it asks you to type JSON, and the validator still
 * judges it.
 */

/* ---------- tiny DOM helpers ---------- */

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function humanize(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

/* ---------- schema helpers ---------- */

/** Resolve a same-document `#/...` $ref against the root schema. */
function resolveRef(ref, root) {
  if (typeof ref !== "string" || !ref.startsWith("#/")) return {};
  let node = root;
  for (const part of ref.slice(2).split("/")) {
    const key = part.replace(/~1/g, "/").replace(/~0/g, "~");
    node = node && node[key];
  }
  return node || {};
}

/** Options [{const, title}] for a scalar enum expressed via oneOf/anyOf-of-const. */
function constOptions(schema) {
  const list = schema.oneOf || schema.anyOf;
  if (!Array.isArray(list)) return null;
  if (!list.every((s) => s && "const" in s)) return null;
  return list.map((s) => ({ value: s.const, label: s.title || String(s.const) }));
}

/** Detect a discriminated union: oneOf of object schemas sharing a const-keyed prop. */
function discriminatedUnion(schema) {
  const list = schema.oneOf || schema.anyOf;
  if (!Array.isArray(list) || list.length < 2) return null;
  const branches = list.map((b) => (b.$ref ? null : b)).filter(Boolean);
  if (branches.length !== list.length) return null;
  if (!branches.every((b) => b.properties)) return null;
  // a discriminator is a property present (with a const) in every branch
  const candidates = Object.keys(branches[0].properties);
  for (const key of candidates) {
    if (branches.every((b) => b.properties[key] && "const" in b.properties[key])) {
      return {
        key,
        branches: branches.map((b) => ({
          value: b.properties[key].const,
          schema: b,
        })),
      };
    }
  }
  return null;
}

/* ---------- the builder ----------
 * Every builder returns { el, read } where read() yields the current JS value
 * (or `undefined` when the field is empty — so the validator naturally reports a
 * missing required value, which is the whole teaching point).
 */

export function buildForm(schema, root = schema, onChange = () => {}) {
  return buildNode(schema, root, onChange);
}

function buildNode(schema, root, onChange) {
  if (!schema || typeof schema !== "object") return rawNode(schema, onChange);
  if (schema.$ref) return buildNode(resolveRef(schema.$ref, root), root, onChange);

  // object with its own properties -> a sub-form (any sibling oneOf/anyOf is a
  // *constraint*, e.g. lookup-record's "exactly one of id/name", left to the
  // validator rather than turned into a widget).
  if (schema.properties || schema.type === "object") return objectNode(schema, root, onChange);

  // scalar enums
  if (Array.isArray(schema.enum)) return enumNode(schema, onChange);
  const opts = constOptions(schema);
  if (opts) return selectNode(opts, schema.default, schema, onChange);

  // unions of objects
  const union = discriminatedUnion(schema);
  if (union) return unionNode(union, root, onChange);

  switch (schema.type) {
    case "array":
      return arrayNode(schema, root, onChange);
    case "number":
    case "integer":
      return numberNode(schema, onChange);
    case "boolean":
      return booleanNode(schema, onChange);
    case "string":
      return stringNode(schema, onChange);
    default:
      if ("const" in schema) return constNode(schema.const);
      return rawNode(schema.default, onChange);
  }
}

/* ----- leaf builders ----- */

function stringNode(schema, onChange) {
  const input = el("input", {
    type: "text",
    class: "sf-input",
    value: schema.default ?? "",
    placeholder: schema.pattern ? `pattern: ${schema.pattern}` : "",
    oninput: onChange,
  });
  return { el: input, read: () => (input.value === "" ? undefined : input.value) };
}

function numberNode(schema, onChange) {
  const input = el("input", {
    type: "number",
    step: "any",
    class: "sf-input",
    value: schema.default ?? "",
    oninput: onChange,
  });
  return {
    el: input,
    read: () => (input.value === "" ? undefined : Number(input.value)),
  };
}

function booleanNode(schema, onChange) {
  const input = el("input", { type: "checkbox", class: "sf-check", onchange: onChange });
  if (schema.default) input.checked = true;
  return { el: input, read: () => input.checked };
}

function constNode(value) {
  const span = el("code", { class: "sf-const", text: JSON.stringify(value) });
  return { el: span, read: () => value };
}

function enumNode(schema, onChange) {
  const names = schema.enumNames; // legacy SEP-1330 titles
  const opts = schema.enum.map((v, i) => ({ value: v, label: names ? names[i] : String(v) }));
  return selectNode(opts, schema.default, schema, onChange);
}

function selectNode(options, dflt, schema, onChange) {
  const select = el("select", { class: "sf-input", onchange: onChange }, [
    el("option", { value: "", text: "— choose —" }),
    ...options.map((o) => el("option", { value: o.value, text: o.label })),
  ]);
  if (dflt != null) select.value = String(dflt);
  return {
    el: select,
    read: () => (select.value === "" ? undefined : coerce(select.value, options)),
  };
}

// selects carry strings; map back to the option's real (possibly non-string) value
function coerce(raw, options) {
  const hit = options.find((o) => String(o.value) === raw);
  return hit ? hit.value : raw;
}

/* ----- array builders ----- */

function arrayNode(schema, root, onChange) {
  if (Array.isArray(schema.prefixItems)) return tupleNode(schema, root, onChange);

  const items = schema.items || {};
  const itemOpts = Array.isArray(items.enum)
    ? items.enum.map((v) => ({ value: v, label: String(v) }))
    : constOptions(items);
  if (itemOpts) return multiSelectNode(itemOpts, schema.default, onChange);

  // generic repeatable list (not used by the demo tools, but keeps the engine honest)
  return repeatListNode(schema, root, onChange);
}

function multiSelectNode(options, dflt, onChange) {
  const boxes = options.map((o) => {
    const cb = el("input", { type: "checkbox", class: "sf-check", value: o.value, onchange: onChange });
    if (Array.isArray(dflt) && dflt.includes(o.value)) cb.checked = true;
    return { o, cb };
  });
  const wrap = el(
    "div",
    { class: "sf-checks" },
    boxes.map(({ o, cb }) => el("label", { class: "sf-checkrow" }, [cb, " " + o.label]))
  );
  return {
    el: wrap,
    read: () => boxes.filter((b) => b.cb.checked).map((b) => b.o.value),
  };
}

function tupleNode(schema, root, onChange) {
  const slots = schema.prefixItems.map((s) => buildNode(s, root, onChange));
  const allowExtra = schema.items !== false;
  const wrap = el(
    "div",
    { class: "sf-tuple" },
    schema.prefixItems.map((s, i) =>
      el("div", { class: "sf-tuple-slot" }, [
        el("span", { class: "sf-tuple-idx", text: s.description || `[${i}]` }),
        slots[i].el,
      ])
    )
  );
  if (!allowExtra) {
    wrap.appendChild(el("p", { class: "sf-hint", text: "items: false — no element beyond the tuple" }));
  }
  return {
    el: wrap,
    read: () => {
      const vals = slots.map((s) => s.read());
      while (vals.length && vals[vals.length - 1] === undefined) vals.pop();
      return vals.map((v) => (v === undefined ? null : v));
    },
  };
}

function repeatListNode(schema, root, onChange) {
  const rows = [];
  const list = el("div", { class: "sf-list" });
  const addBtn = el("button", { type: "button", class: "button sf-add", text: "+ add item" });
  function addRow() {
    const node = buildNode(schema.items || {}, root, onChange);
    const remove = el("button", { type: "button", class: "button sf-remove", text: "×" });
    const row = el("div", { class: "sf-list-row" }, [node.el, remove]);
    const entry = { node, row };
    remove.addEventListener("click", () => {
      list.removeChild(row);
      rows.splice(rows.indexOf(entry), 1);
      onChange();
    });
    rows.push(entry);
    list.appendChild(row);
    onChange();
  }
  addBtn.addEventListener("click", addRow);
  const wrap = el("div", {}, [list, addBtn]);
  return {
    el: wrap,
    read: () => {
      const vals = rows.map((r) => r.node.read()).filter((v) => v !== undefined);
      return vals.length ? vals : undefined;
    },
  };
}

/* ----- object & union builders ----- */

function objectNode(schema, root, onChange) {
  const props = schema.properties || {};
  const required = new Set(schema.required || []);
  const fields = [];
  const rows = Object.entries(props).map(([name, propSchema]) => {
    const field = buildNode(propSchema, root, onChange);
    fields.push({ name, field });
    return fieldRow(name, propSchema, required.has(name), field.el);
  });
  const constraintHint = constraintNote(schema);
  const wrap = el("div", { class: "sf-object" }, [...rows, constraintHint]);
  return {
    el: wrap,
    read: () => {
      const out = {};
      for (const { name, field } of fields) {
        const v = field.read();
        if (v !== undefined) out[name] = v;
      }
      return out;
    },
  };
}

// surface object-level constraints that aren't form structure (so the form
// explains why the validator might reject an otherwise-filled object)
function constraintNote(schema) {
  const notes = [];
  if (Array.isArray(schema.oneOf)) notes.push("exactly one of the oneOf branches must match");
  if (schema.additionalProperties === false) notes.push("no extra properties allowed");
  if (schema.if) notes.push("conditional (if/then) rules apply");
  if (!notes.length) return null;
  return el("p", { class: "sf-hint sf-constraint", text: "Constraint: " + notes.join("; ") });
}

function unionNode(union, root, onChange) {
  const body = el("div", { class: "sf-union-body" });
  let active = null;
  const select = el(
    "select",
    {
      class: "sf-input",
      onchange: () => {
        render(select.value);
        onChange();
      },
    },
    [
      el("option", { value: "", text: "— choose —" }),
      ...union.branches.map((b) => el("option", { value: b.value, text: String(b.value) })),
    ]
  );
  function render(value) {
    body.replaceChildren();
    active = null;
    const branch = union.branches.find((b) => String(b.value) === value);
    if (!branch) return;
    // render the branch's object, minus the discriminator property (set by select)
    const sub = { ...branch.schema, properties: { ...branch.schema.properties } };
    delete sub.properties[union.key];
    const node = objectNode(sub, root, onChange);
    active = { value: branch.value, node };
    body.appendChild(node.el);
  }
  const wrap = el("div", { class: "sf-union" }, [
    el("label", { class: "sf-union-label" }, [`${union.key}: `, select]),
    body,
  ]);
  return {
    el: wrap,
    read: () => {
      if (!active) return undefined;
      return { [union.key]: active.value, ...active.node.read() };
    },
  };
}

function rawNode(dflt, onChange) {
  const ta = el("textarea", {
    class: "sf-input sf-raw",
    rows: 3,
    placeholder: "raw JSON",
    oninput: onChange,
  });
  if (dflt !== undefined) ta.value = JSON.stringify(dflt, null, 2);
  return {
    el: ta,
    read: () => {
      if (ta.value.trim() === "") return undefined;
      try {
        return JSON.parse(ta.value);
      } catch {
        return ta.value; // let the validator complain about the type
      }
    },
  };
}

/* ----- field chrome ----- */

function fieldRow(name, schema, required, control) {
  const title = schema.title || humanize(name);
  const label = el("div", { class: "sf-label" }, [
    el("span", { class: "sf-name", text: title }),
    required ? el("span", { class: "sf-req", text: "required" }) : null,
    el("code", { class: "sf-key", text: name }),
  ]);
  const hint = schema.description ? el("p", { class: "sf-hint", text: schema.description }) : null;
  return el("div", { class: "sf-field" }, [label, control, hint]);
}

/* ---------- validation rendering ---------- */

/**
 * Render a validator result into `target`. Expects the @cfworker/json-schema
 * shape: { valid: boolean, errors: [{ instanceLocation, keywordLocation, error }] }.
 */
export function renderErrors(result, target) {
  target.replaceChildren();
  const ok = result && result.valid;
  target.appendChild(
    el("p", { class: "sf-verdict " + (ok ? "is-valid" : "is-invalid") }, [
      el("span", { class: "sf-verdict-mark", text: ok ? "✓" : "✗" }),
      ok ? " Valid against the schema" : " Invalid against the schema",
    ])
  );
  if (ok) return;
  const errors = (result && result.errors) || [];
  // dedupe by location+message; cfworker emits one per failing sub-branch
  const seen = new Set();
  const list = el("ul", { class: "sf-errors" });
  for (const e of errors) {
    const where = e.instanceLocation && e.instanceLocation !== "#" ? e.instanceLocation : "(root)";
    const msg = `${where} — ${e.error}`;
    if (seen.has(msg)) continue;
    seen.add(msg);
    list.appendChild(el("li", { text: msg }));
  }
  if (list.childElementCount) target.appendChild(list);
}
