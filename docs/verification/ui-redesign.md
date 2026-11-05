# Meridian UI redesign

The interface uses adapted shadcn/ui New York components with Radix primitives,
React and Vite. The shared theme uses neutral surfaces, dark readable text,
restrained teal accents and consistent controls. No external font requests or
new application service is required.

Customer screens retain chat, saved conversations, citations, source previews,
part attachments, the full searchable/filterable catalog, drawings and their
pan/zoom/sheet controls, 3D examples and downloads, source facts, and translated
notes. Engineering reviews, receipts, checks and history remain in Debug.
Existing source and review behavior is preserved. No extraction, CAD generation,
model choice, approval policy or source evidence changed for this redesign.

The parts catalog is a compact table instead of a collection of large cards.
Additional filters remain collapsed. Part details retain their standard summary
sections. Real keyboard-accessible tabs select the existing viewers. Chat history
uses a focus-trapping dialog with Escape and focus restoration.

Verification uses the existing customer/Debug browser suite, plus interaction
checks for sending a message, source/attachment navigation, conversation retained
on Back, copying, dialog keyboard behavior, keyboard part tabs, drawing zoom/fit,
asset filtering/reset and screenshots at desktop, laptop and mobile sizes. The
new chat interaction check mocks only its HTTP transport; it makes no paid API
or answer-quality claim. Existing history checks still exercise persistence,
reload and deletion against the backend. Builds and browsers run on Actions,
in sequence; a matching hash-verified static bundle is downloaded for local use.

Run results and screenshots are recorded after integration verification.
