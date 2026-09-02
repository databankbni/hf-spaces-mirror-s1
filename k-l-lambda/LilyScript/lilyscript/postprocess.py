"""Lilylet output post-processing (vendored from deep-starry, torch-free).

Cleans raw generated Lilylet text for readability:
  - move each `[r:x/y]` stream marker from the measure head to a trailing
    comment `% r:x/y` at the measure end (the line ending in `|`),
  - insert a blank line after the metadata block,
  - insert a blank line at every measure boundary.

Because a blank line is inserted at each measure boundary, the postprocessed
text is naturally segmented measure-by-measure — which is what the editor pane
displays as generation streams in.

Source: deep-starry/starry/lilylet/patchyGenerator.py (postprocess / _STREAM_RE).
"""

import re


# matches a stream marker like `[r:12/34]` (and a trailing partial `[r:12/` at EOF);
# group 1 captures the `x/y` payload.
_STREAM_RE = re.compile(r'\[r:(\d+/\d*)\]?')


def postprocess (text: str) -> str:
	lines = [ln.rstrip() for ln in text.split('\n')]
	out = []
	meta_done = False
	pending = None		# marker payload waiting to be attached at the measure end

	for ln in lines:
		# extract the stream marker (sits at the measure head); remember its
		# payload and strip the marker text from the line.
		m = _STREAM_RE.search(ln)
		if m:
			# a still-pending marker means the previous measure had no barline
			# (e.g. truncated); keep it as a standalone comment so it isn't lost.
			if pending is not None:
				out.append('% r:' + pending)
			pending = m.group(1)
			ln = _STREAM_RE.sub('', ln).rstrip()

		# metadata lines: `[field "..."]` headers and leading `%<style>` comments
		# (the --styles-in-comments format). Both belong to the meta block.
		is_meta = (ln.startswith('[') and ln.endswith(']')) or (ln.startswith('%') and not ln.startswith('%%'))
		# blank line once the metadata block ends and the body begins
		if not meta_done and out and not is_meta and ln:
			out.append('')
			meta_done = True

		is_measure_end = ln.endswith('|')
		if is_measure_end and pending is not None:
			ln = ln + ' % r:' + pending
			pending = None

		out.append(ln)

		# blank line after a measure-ending line
		if meta_done and is_measure_end:
			out.append('')

	# any marker left pending at EOF -> attach as a trailing comment
	if pending is not None:
		out.append('% r:' + pending)

	# collapse runs of blank lines, trim leading/trailing blanks
	cleaned = []
	for ln in out:
		if ln == '' and (not cleaned or cleaned[-1] == ''):
			continue
		cleaned.append(ln)
	return '\n'.join(cleaned).strip('\n') + '\n'
