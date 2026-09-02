# Beiing Human — Support Knowledge Base (Chatbot Source Document)

**Version:** 2.3 · Written from the code actually deployed to production — web app
`customer-app-react @ origin/master`, backend `backend-app-nodejs-tierb @ origin/main` and the
email-intake Lambda `teirA-parse-email-prod` — cross-checked against the support inbox, August 2026.

**Changed in 2.3:** added file-type rules including iPhone HEIC photos (5.7), the Pay Control column
and bulk assign (6.2, 6.5), and document annotation — stamps and notes (7.8).

**Purpose:** This is the single source document behind the Beiing Human FAQ chatbot at `app.beiinghuman.com/FAQ`.
**Escalation:** For anything not covered here, email **support@beiinghuman.com**.

> Everything here describes behaviour that is **live on production**. Features that exist only on a
> development or feature branch are deliberately excluded, because customers cannot see them yet.

> **Note for the chatbot:** Answer only from this document. When a question is about a feature that is
> controlled by a company setting or a user role, say so explicitly and name the setting or role — most
> "why can't I see / do this?" questions are permission or setting questions, not bugs.

---

## 1. Glossary and alternate names

Users ask about the same things using different words. These are the same:

| Official name | Also called |
|---|---|
| Human Review screen | HIL screen, human-in-the-loop, review screen, canvas, document review screen, coding screen |
| Documents tab | document list, queue, inbox, grid, table |
| To Review tab | new documents, unprocessed, needs coding |
| In Review tab | waiting for approval, out for approval, pending approval, sent for approval |
| Pull Back | recall, unsend, take back, bring back an invoice |
| Q&A | question, ask a question, query on an invoice, raise a question |
| INYA report | Invoices Not Yet Approved, approver report, aging approvals report |
| Approval Policy | approval workflow, routing, approval levels, approval matrix |
| Match → Purchase Order | Match PO, PO matching, 2-way match, subcontract matching, Match SC |
| Match → Delivery Ticket | Match DT, delivery ticket matching, 3-way match, attach delivery ticket |
| Exportable File | export file, CSV export, ERP file, FSI file |
| Send to ERP | push to ERP, sync to ERP, post to ERP |
| Sub Admin | support role, secondary admin, back-up admin |
| AP Admin | company admin, primary admin, account owner |
| Code Visibility | restrict GL accounts, hide GL accounts, limit codes per user |
| COI Tracker | compliance tracker, insurance tracker, certificate tracking, COI dashboard |
| COI | certificate of insurance, cert, ACORD 25, insurance certificate |
| Don't track (a vendor) | archive a vendor, stop chasing, exclude from COI, do not track |
| Coding | account coding, job costing, GL/job/cost coding |
| Job Id | Project Id (on Vista and Spectrum) |
| Cost Id | Cost Code, Item (on Vista and Spectrum) |
| Transaction Date | GL Date (on Vista) |

**Document types the platform handles:** Invoice, Receipt, Delivery Ticket, Purchase Order (PO),
Quote (also called Estimate), G702 (AIA progress billing).

---

## 2. Supported ERP integrations

Beiing Human supports these ERP systems. The ERP you select changes which fields, settings and
features are available.

- **Foundation** (Foundation Software)
- **ViewPoint Vista** (Trimble Vista)
- **ViewPoint Spectrum**
- **QuickBooks Desktop**
- **QuickBooks Online**
- **Deltek ComputerEase**
- **RentalMan**
- **Accounting Seed**
- **Other** (no ERP connection — file export only)

**Integration styles:**
- **File-based integration** — Beiing Human produces an export file (.csv / .txt) that you import into
  the ERP. Fully approved documents get the status **Approved**.
- **API-based integration** — Beiing Human writes directly into the ERP. Fully approved documents get
  the status **Verified**, then **In ERP** once the ERP accepts them.

This is the *only* difference between the **Approved** and **Verified** statuses: Approved =
file-based, Verified = API-based. Both mean "every required approver has approved."

### How to connect an ERP
As AP Admin or Sub Admin:
1. Click the dropdown next to your name (top-right) → **Profile**.
2. Choose your ERP under **Select ERP Option** (bottom-left of the Profile page) → **Save**.
3. Go to **Integration** in the top navigation → **Connect** → follow the on-screen steps.

You must disconnect an existing integration before you can change the ERP type.

**What disconnecting does to your approval policy — the exact rule:**
- **Disconnecting and reconnecting the same ERP** only **disables** the policy. The policy itself is
  kept, so reconnecting restores your approval flow untouched. Re-check that the policy is Active
  afterwards.
- **Changing to a different ERP type** **deletes** the policy. Its levels are built on ERP-specific
  entities (jobs, vendors) that do not carry over, so it has to be rebuilt from scratch.

Disconnecting also clears the synced purchase orders, tax codes and reviewers for that ERP; they come
back on the next sync after you reconnect.

---

## 3. Roles and permissions

### 3.1 Built-in roles

| Role | What it is for |
|---|---|
| **AP Admin / Admin** | The company's primary administrator. Full access, including managing the AP Admin account. |
| **Sub Admin** (stored as the "Support" role) | Nearly identical to AP Admin. Can manage company settings, users, approval policies, integrations, and see all company documents. **Cannot create, edit, or delete the AP Admin account, and cannot delete their own account.** |
| **Accountant** | AP / accounting staff. Codes, reviews and processes documents. |
| **Owner** | Company ownership view; same document tabs as Accountant. |
| **C Level** (C_Level) | Executive approver. With the "assign documents" permission they also get a **Company Documents** tab showing all company documents and the ability to assign documents to other users. |
| **Manager** | Project manager / field approver. Approves and (if allowed) codes documents routed to them. |
| **Vendor** | External vendor portal user. Sees only their own documents. |

**Answer to "what is a Sub Admin?"** — A Sub Admin has nearly the same permissions as the AP Admin:
manage company settings, manage users, configure approval policies, manage integrations, and access
all company documents. The only things a Sub Admin cannot do are create/edit/delete the AP Admin
account and delete their own account. In the user list a Sub Admin appears with the role label
"Sub Admin".

### 3.2 Custom roles

AP Admins (and anyone with the *Create New Roles* permission) can create additional named roles under
**Users → User Roles → Create New Role**. Role names may contain letters and spaces only.

Each role is a set of switches:

| Permission | What it grants |
|---|---|
| Update Users | Add, edit and remove users |
| Update Company Profile Settings | Change Settings / company toggles |
| Update Policy | Create and edit approval policies (also unlocks the **Policy** tab) |
| Update Integration | Connect / disconnect ERP integrations |
| On Hold Document | Put documents on hold (also controls whether the **On Hold** tab is visible) |
| Reject Document | Reject documents |
| Upload Document | Upload documents |
| Pull Back Document | Recall documents already sent for approval |
| Consolidate Line Items | Combine line items on a document |
| Manual Approvers | Override the approval policy on an individual document (Custom Approval) |
| Create New Roles | Create new custom roles (requires Update Users, which is switched on automatically) |
| Update Role Configurations | Edit the permissions of existing roles (requires Update Users) |

Turning **Update Users** off automatically turns off *Create New Roles* and *Update Role Configurations*.

### 3.3 Adding, inviting and removing users

**Invite a user:**
1. Dropdown next to your name (top-right) → **Users**.
2. **Sync Users** / **Sync from ERP** imports the user list from your connected ERP.
   *This overrides your existing ERP users — confirm the prompt before proceeding.*
3. Click **Register** next to a synced user to email them an invitation, or
4. Click **Add User** (top-right) for anyone not in the ERP, choose their role, and send the invitation.
5. The user receives an email invitation, sets a password, and can then be added to approval policies.

**Delete a user:** Users screen → **Delete** next to the user → confirm. The user immediately loses
access. A Sub Admin cannot delete themselves or the AP Admin.

**A person who works for several companies** needs a separate login per company. Ask IT for an email
alias (e.g. `JacksonWater@yourcompany.com` as an alias of `Jackson@yourcompany.com`) and register one
account per alias.

**Getting user-management access:** ask your AP Admin to go to **Users → User Roles**, click the edit
icon on your role, and enable **Update Users** (or whichever permission you need).

---

## 4. Why two people see different documents (most common support question)

If two users are looking at the same tab and seeing different documents, work through this list in
order. There are five separate reasons, and they stack.

**1. An active column filter.** The Documents grid keeps a filter per user, and it *persists* — it is
still applied when you come back tomorrow. A small **filter icon appears next to the column header**
when a filter is active on that column.
- Filterable columns: **Vendor Name, Job ID, Equipment No, Status, File Uploaded By, Mentions,
  Q&A Created At, Exported At**.
- Only **one column filter** applies at a time — setting a filter on a new column replaces the old one.
- To clear it: open the filter panel (funnel icon in the grid toolbar) and click **Clear**.
  You do **not** need to type a filter value first; **Clear** on its own removes the filter.
  **Save** applies a filter, **Clear** removes it.

**2. The tab you are on.** Each tab shows a different slice. "To Review" and "In Review"
are different populations, and a document sitting in Q&A or On Hold leaves both of them.

**3. Your role's tab set.** Roles do not all get the same tabs. Accountant, Owner and
Sub Admin get a **Classify/Split** tab that approver roles do not. The **On Hold** tab only appears
for roles with the *On Hold Document* permission. **Company Documents** only appears for C Level users
who have the document-assignment permission.

**4. Your role decides whether you see the company queue or only your own.**
- **Admin, Owner, Accountant, Sub Admin and Vendor** read from the **company** document queue —
  they see every document in the company (vendors are separately restricted to their own).
- **Manager, C Level and custom roles** read from their **own** queue — they only see documents the
  approval policy has actually routed to them. If a document is at a level you are not part of, it is
  not in your list, even though the person who uploaded it still sees it.

**5. Document Assignment (accountants only).** This is the one that most often surprises people.
Settings has a **Document Assignment** mode with three values:
- **Default** — every accountant sees every company document.
- **Auto** — each new document is automatically assigned to the accountant with the fewest documents
  (load balancing). On Vista, assignment can instead follow the PayControl rules configured per
  accountant.
- **Manual** — documents are assigned to an accountant by hand.

In **Auto** or **Manual** mode, an accountant only sees documents that were assigned to **them**. Two
accountants at the same company will each see roughly half the queue and that is working as designed.

> **Important:** documents that were created *before* the company switched away from Default have no
> accountant assigned, so after the switch they are visible to no accountant at all — only to the
> Owner / Admin / Sub Admin roles. If a company turns on Auto or Manual, expect older documents to
> drop out of accountants' lists.

### Known discrepancy: the daily email count can be higher than what you see

The daily reminder email and the Documents screen do **not** apply the same rules. The email counts the
whole company queue for an accountant; the Documents screen additionally applies the Document
Assignment filter above. So an accountant at a company using **Auto** or **Manual** assignment can be
told "4 pending approvals" and see only the 2 assigned to them. The screen is showing the correct,
intended set; the email is over-counting.

If a user reports the email number not matching the screen, that is the expected cause. Confirm with
support which assignment mode the company is on.

---

## 5. Getting documents into Beiing Human

### 5.1 Upload from the web app
Log in and use the upload / import area on the Documents screen. Drag and drop files, or click to
browse. You choose the document type when uploading.

### 5.2 Email submission
Forward or send documents to **process@documents.beiinghuman.com** from your company email address.
Your company's dedicated intake address is shown in your Beiing Human profile.

### 5.3 Splitting a multi-document PDF
If one PDF contains several invoices there are three ways in, and they all end at the same place —
the **Classify/Split** tab, where you join or separate pages before they are processed.

1. **By email:** put the word **Split** (or "split") anywhere in the subject line.
2. **At upload:** use the **Split PDF** button in the upload area.
3. **After the fact, for a document already in Beiing Human:** open it and change **Document Type**
   to **Split**. It moves straight to Classify/Split.

**Important:** the AI does **not** reliably detect on its own that a PDF holds several invoices. If
you email a combined PDF without "split" in the subject, expect it to come in as one document — then
use method 3 to fix it. That is the normal workflow, not an error.

**Why "Split" might not be in the Document Type dropdown:** the option only appears for a
**multi-page PDF**. A single-page document, or an image (JPG/PNG) rather than a PDF, cannot be split.

Requires the **Doc Splitter** setting.

### 5.3.1 What the Document Type dropdown offers
On the Human Review screen the Document Type dropdown is only editable by **Accountant, Owner and
Sub Admin** roles. The options it lists are:

| Option | Shown when |
|---|---|
| **Invoice** | Always |
| **Quote** | ERP is **Foundation or QuickBooks Desktop** *and* Quote and PO Import is on |
| **G702** | G702 Import is on |
| **Receipt** | Receipt Import is on |
| **Delivery Ticket** | Delivery Ticket Import is on |
| **Split** | The document is a multi-page PDF |

Note the Quote row: even though the **Quote and PO Import** setting can be switched on for Vista and
Spectrum, the Quote option in this dropdown is limited to Foundation and QuickBooks Desktop.

Changing the type re-processes the document and moves it to the matching list, with the row
highlighted so you can see where it went.

### 5.4 Credit card receipts
Users photograph the receipt with their phone and submit it. The photograph is the source of truth —
Beiing Human does **not** import transactions from your bank or card provider as documents. If a bank
account is connected, the card feed is only used to *nudge*: when a card transaction has no matching
receipt, the user gets an email reminder to submit one.
Requires the **Receipt Import** setting. A **Default Receipt Vendor** can be configured so receipts
are pre-assigned to a chosen vendor.

### 5.5 Duplicate detection
Two independent checks, each with its own setting:
- **Duplicate Detection on File Processing** — image-hash based. Catches the *same file* being uploaded
  again and warns before it is processed, so you can discard the copy.
- **Duplicate Bill No Check** — catches the *same bill/invoice number for the same vendor*, even if the
  file is different.
Duplicates show the **Duplicate** status and let you compare Previous vs New before deleting one.

### 5.6 Documents that fail to process
A document can fail with a reason such as "Unsupported Document" — usually a file that is not a
readable invoice/receipt (a logo image, an email signature graphic, a statement, a terms-and-conditions
page). The failure reason is shown on the document and emailed to your AP team. Re-submit a clearer
scan, or delete the item if it should not have been sent.

### 5.7 What file types Beiing Human accepts
**PDF, JPG and PNG** are the readable formats. A PDF may be multi-page; images are treated as a single
page.

**iPhone photos (HEIC) — emailing works, dragging into the web app does not.** This distinction catches
people out, so state it plainly:

| How the file arrives | HEIC accepted? |
|---|---|
| **Emailed** to your Beiing Human intake address | **Yes.** Converted to JPG automatically on arrival. Nothing to change on the phone. |
| **Uploaded** in the web app, or by a vendor in the vendor portal | **No.** Refused as an unsupported type. |

If someone needs to upload an iPhone photo through the web app, either email it in instead, or set the
phone to save photos as JPG: **Settings → Camera → Formats → Most Compatible**.

**Never readable, however they arrive:** spreadsheets (.xlsx, .xls, .csv), Word documents (.doc, .docx),
plain-text files (.txt), videos (.mp4, .mov), and email signature graphics (.gif, .emz, .wmf). Send the
invoice itself as a PDF or a photo. A spreadsheet backing up an invoice cannot be read even when the
invoice PDF alongside it processes normally.

**Size limits** are in section 21.

---

## 6. The Documents screen

### 6.1 Tabs

| Tab | What it contains |
|---|---|
| **To Review** | Documents that still need attention — not yet sent for approval, not rejected, not on hold, not in Q&A, not approved. |
| **In Q&A** | Documents with an open question. Locked until the question is resolved. |
| **In Review** | Sent for approval and waiting on an approver. |
| **On Hold** | Parked for discussion. *Only visible to roles with the On Hold permission.* |
| **Classify/Split** | Batches from the document splitter, waiting to be joined/separated. *Accountant, Owner and Sub Admin only.* |
| **Rejected** | Rejected by an approver and sent back. |
| **Approved** | Fully approved, not yet exported / sent to the ERP. |
| **Exported** | Already exported to (or accepted by) the ERP. |
| **Company Documents** | Every document in the company. *C Level users with the document-assignment permission only.* |

Top-level navigation: **Dashboard**, **Documents**, **Integration**, **Policy** (with the Update Policy
permission), **Budgets** (with Job Budget Management on QuickBooks Desktop), **Downloads**.

### 6.2 Columns
Vendor Name, Document No, Document Type, Document Date, Due Date, Amount Due, PO Number, Job ID
(Document ID for vendors), Equipment No, Status, **Sitting With**, **Pay Control**, Paid, Received At,
File Uploaded By, Created By, Comment, Mentions, Q&A Created At, Exported At, Actions.

**Sitting With** names the person or step the document is currently waiting on — the fastest way to
answer "who has this?" without opening it.

**Pay Control** appears only for **Vista** and **Foundation** companies, and only for **AP Admin
(Owner)**, **Accountant** and **Support** users. See 6.5.

### 6.3 Filtering, searching and sorting
- **Column filter** — funnel icon in the grid, one column at a time, **Save** to apply, **Clear** to
  remove. Persists across sessions until cleared.
- **Keyword search** — the search bar searches the visible document set.
- **Advanced Search** — a separate screen that searches across all statuses at once.
- **Sort** — click a column header. Sorting and page size are remembered.

### 6.4 Deleting documents
Select one or more documents and use **Delete**. You will be asked to confirm.
- A delivery ticket that is attached to an invoice cannot be deleted — detach it first.
- Documents are deleted from the list you are in; there is no company-wide bulk purge.

### 6.5 Pay Control
The **pay control** is the person in your ERP who is responsible for paying an invoice — the ERP's own
`accountant` value on the document. Beiing Human shows it so AP can sort and hand off work without
opening each invoice.

**Who sees it:** **Vista** and **Foundation** companies only, and only **AP Admin (Owner)**,
**Accountant** and **Support** users. If the column is missing, check the company's ERP and your role
before treating it as a bug — this is the usual explanation.

**Where the values come from:** the list of pay controls synced from your ERP. If a name is missing from
the filter or the assign list, it has not been synced from the ERP yet — sync the ERP, do not retype it.

**Assigning in bulk (Foundation only):** tick one or more documents on the Documents screen and an
**Assign Pay Control** button appears next to Delete and Download Files. Choose a pay control and it is
applied to every ticked document at once; the list refreshes and the selection clears. The button only
exists when rows are ticked, and only for Foundation — **Vista companies can see the column but cannot
bulk-assign from it.**

---

## 7. The Human Review (HIL) screen

Open a document from any tab to reach the review screen. It shows the document image on one side and
the extracted data on the other.

### 7.1 Sections
- **Document Details** — vendor, document number, dates, totals, PO number, terms/discount, payment
  terms (if enabled).
- **Account Details** — the header-level coding: GL Account, Job Id, Cost Id, Cost Type, Phase,
  Equipment No, Service Code, GL Division, Work Order, Type, PayControl.
- **Line Items** — per-line description, quantity, UOM, unit price, amount, tax, and the same coding
  fields as Account Details.
- **Payment Details** — payment status, type, check number, amount, date.
- **Activity** — the full audit trail.
- **Comments / Q&A** — discussion on the document.

Anything the AI extracted can be corrected by hand. Human edits always win.

### 7.2 Confidence colours
Fields and boxes are colour-coded by the AI's confidence:
- **Green** — high confidence
- **Orange / Yellow** — moderate
- **Red** — low

With **Confidence score based Pointing** enabled the thresholds are:
delivery tickets — green ≥85%, yellow 55–84%, red <55%; all other documents — green ≥99%,
yellow 85–98%, red <85%.

Colour is statistical, not a guarantee. A red box can hold correct data and a green box can hold wrong
data — always review.

### 7.3 Process as Total vs Process as Line
- **Process as Line** captures every line item individually (default).
- **Process as Total** collapses the document into a single line from the invoice total.
The company default is set in Settings; you can flip it per document on the review screen.

### 7.4 Coding help
- **Save Vendor Codes** — remembers the coding used last time for that vendor and pre-fills it.
- **Default Coding** — pulls the vendor's default coding from the ERP (Foundation, Vista, Spectrum,
  RentalMan).
- **AI Code Prediction** — AI-suggested coding.
- **Job Budget based Coding** — codes from the job budget (Foundation and Vista).
These four are mutually exclusive in places: Default Coding, AI Code Prediction and Job Budget based
Coding cannot all be on at once — turning one on disables the others.

**If your POs lack coding detail:** turn *off* PO-based coding and turn *on* "Save Vendor Codes" so the
last coding for that vendor is reused.

### 7.5 Validations
- **Line Items Total Matching** — line item totals must equal the document total.
- **Line Items Amount Calculation** — each line's amount must equal quantity × unit price.
- **Miscellaneous Amount Calculation** (Vista) — header total must equal the sum of line amounts minus
  the miscellaneous amount.
- **Coding Validations** — validates coding against the ERP.
- **Validations for Last Approver Only** (Vista) — applies coding validations only to the final
  approver instead of every approver.

If the document total does not match the line item total you get a prompt and can still proceed
deliberately.

### 7.6 Accepting a field the AI flagged
Each field has a checkbox beside it. **You can tick that checkbox even when the value does not match
what is printed on the image** — for example an old invoice where you deliberately want a different
transaction date. Ticking it confirms the value you have entered; it is not a claim that the image
says the same thing. To accept everything at once, use **Verify All** at the bottom left.

This is the answer to "it will not let me move forward / it keeps flagging this field."

### 7.7 Other review-screen actions
**Reset** (rebuild line items from the image),
**Fetch PO / Fetch Subcontract / Fetch Work Order** (overwrite the current data with the ERP record —
you are asked to confirm because it discards your edits), rotate image, save document state.

### 7.8 Annotating a document (stamps and notes)
Some teams need a mark on the invoice image itself — a tax-exempt stamp, a received date, a job number
written in the margin — so that whoever sees the document later in the ERP sees it too.

**Annotate Document** on the review screen opens annotation mode, which gives two tools:

- **Place a stamp** — choose from **TAX EXEMPT**, **RECEIVED**, **APPROVED** or **VOID**, then click
  where it should sit on the page.
- **Write a note** — free text placed anywhere on the page. The box is prompted with
  "Job / work order no." because that is the most common use, but any text is allowed.

Click **Save** to keep the marks, or close annotation mode to discard them.

**What "saved" means, and why it matters:** the marks are burned into the document image, not stored as
a separate layer. Once saved they travel with the document everywhere it goes afterwards — the review
screen, the downloaded file, and the copy that reaches your ERP. That is the point of the feature, and
it is also why a stamp cannot simply be peeled off later: to change a mark, re-annotate and save again.

**Who can do it:** anyone who can open the document for review. It is not restricted by ERP.

---

## 8. Matching

### 8.1 The Match button
All matching is done from the single **Match** button on the Human Review screen. It opens a dropdown
with up to four choices — which ones appear depends on your ERP, your settings and the document type:

| Option | Appears when |
|---|---|
| **Purchase Order** | PO / Subcontract Matching is on, and the document is not a G702 |
| **Delivery Ticket** | Delivery Ticket Import is on, and the document is an Invoice or G702 |
| **Subcontract** | PO / Subcontract Matching is on |
| **Work Order** | Vista only, Work Order setting on, and the document is not a Quote, Delivery Ticket or PO |

If the whole **Match** button is greyed out, neither PO/Subcontract Matching nor Delivery Ticket
Import is enabled for you.

### 8.2 Invoice to Purchase Order / Subcontract
**Match → Purchase Order** (or **Subcontract**). The invoice-to-PO comparison appears in the top
middle of the screen; the **eye icon** opens side-by-side comparison tabs. The PO view shows, per
line: Amount, Received, Remaining and Status, so you can see what is left open on the PO.
Requires the **Purchase Order / Subcontract Matching** setting. Available on Foundation, Vista,
Spectrum and RentalMan.

### 8.3 Invoice to Delivery Ticket
**Match → Delivery Ticket.** Beiing Human then suggests eligible delivery tickets.

**Before the Delivery Ticket option is even selectable, the invoice needs:**
1. An **invoice / document number** — it cannot be blank or "-".
2. A **total amount** — it cannot be blank or "-".

**A delivery ticket then only appears as a suggestion when:**
3. The vendor on the delivery ticket **matches the vendor on the invoice**.
4. The delivery ticket date is **the same as or earlier than** the invoice date.

So "the Delivery Ticket option is greyed out" is almost always a missing invoice number or total,
while "the option works but no tickets are listed" is a vendor or date mismatch. Use
**Show All Delivery Tickets** to browse past the suggestions.
Requires the **Delivery Ticket Import** setting (Foundation, Vista, Spectrum).

### 8.4 Why line items don't match
Common and usually harmless causes:
- Tax lines are on the invoice but not on the delivery ticket
- Rounding or unit-of-measure (UOM) differences
- Partial deliveries
Use the side-by-side visual and table views to check unit price and quantity.

---

## 9. Approvals

### 9.1 Approval policy
Created under the **Policy** tab (needs the *Update Policy* permission). A policy can be based on:
- **Total** (invoice amount)
- **Vendor**
- **Job Id / Project Id**
- **Job and Total**

A policy is built from **Levels**. Each level lists the approvers required at that level; documents move
level by level. Amount thresholds define which level range applies (a maximum of 0 means infinity).
A **Default Approver** can be set: when the invoice total exceeds the threshold, it is also sent to that
additional approver at the end.

**Populate Approvers** imports your job-based approver structure from the ERP and **overrides your
existing policy levels**. Only project managers already registered as managers in Beiing Human are
included, so register missing PMs first. Policy creation only becomes available once Manager / C Level
registration is complete.

Saving a policy overrides the previous one. Making a policy inactive disables the approval workflow.

### 9.2 What an approver can do
Approve, reject (returns it to the previous person), put **On Hold**, add comments visible to all
approvers, attach delivery tickets or supporting documents, modify content or line items (if permitted),
use **Verify All**, and raise a **Q&A** question.

**Manager as First Approver** — when on, a manager can upload and code a receipt first; after their
approval it goes to AP for the standard workflow. When off, everything a manager uploads goes straight
to AP.
**Manager Content Editing** — controls whether managers may change document content.

### 9.3 Custom Approval (overriding the policy for one document)
On the Human Review screen, use the dropdown attached to the **Approve** button → choose
**Custom Approval** → select the users whose approval you want. Requires the *Manual Approvers*
permission.

### 9.4 Pull Back (recalling a document)
Use this when a document has already gone out for approval and you need it back.
1. Go to the **In Review** tab (the approval queue) and find the document.
2. Click the **Pull Back** icon (↩) in the **Actions** column.
3. Confirm in the popup.
4. The document returns to your list, highlighted.
5. Correct it and send it for approval again.
Requires the *Pull Back Document* role permission. The pull back is recorded in the audit trail.

### 9.5 Q&A
Raise a question on a document without changing its approval status.
- Assign the question to a specific user (e.g. a PM: "Whose job is this?").
- The document is **locked** while the question is open and moves to the **In Q&A** tab.
- Every question and answer is stored in the Activity / audit trail.
- Once resolved, the approval workflow resumes where it paused. For an approver-role question the
  document unlocks for **everyone at that approval level**, not just the one person.

**Who can resolve a question?** The **Resolve** button appears if any one of these is true:
1. You raised the question, **or**
2. You have the **same role** as the person who raised it, **or**
3. You and the raiser are both in the AP-side group — **Owner, Accountant or Sub Admin** — in which
   case any of those three can resolve the others' questions.

So a question raised by one accountant can be resolved by another accountant, or by the Owner or a
Sub Admin. If you cannot see the Resolve button, you fall outside all three cases — ask the raiser or
someone sharing their role.

### 9.6 Rejections
A rejected document moves to **Rejected**. The approver's comments and any attached evidence travel
with it. AP can correct and resend, or email the vendor directly from inside Beiing Human. All of it
stays in the audit trail.

### 9.7 Audit trail
Every action is logged with user and timestamp: uploaded, created, updated, rotated, approved,
rejected, put on hold, commented, attachment added/removed, question raised, pulled back, added to
queue, sent to ERP, export succeeded, export failed. Open it from the **Activity** panel on the
Human Review screen.

---

## 10. Document statuses

| Status | Meaning |
|---|---|
| **Processing** | The AI is still extracting the document. |
| **Pending** | Not yet approved by any role or level. |
| **In Review** | Approved by the current role and sent to the next level/role. |
| **In Q&A** | An open question is locking the document. |
| **On Hold** | Parked for discussion or clarification. |
| **Rejected** | An approver sent it back. |
| **Approved** | *File-based integrations.* Approved by every required role/level. |
| **Verified** | *API-based integrations.* Approved by every required role/level. |
| **In ERP** | Accepted by the ERP. |
| **Exported** | An export file has been generated for it. |
| **Attached** | A supporting document (e.g. delivery ticket) has been attached. |
| **Duplicate** | Flagged by duplicate detection. |
| **Error / Failure** | Processing or ERP submission failed; the reason is shown on the document. |

---

## 11. Getting documents out — export and ERP

### 11.1 File-based export (e.g. Foundation FSI Importer)
1. Approve the document — it appears in the **Approved** tab.
2. Select it and click **Exportable File**.
3. Download the .csv / .txt file.
4. In Foundation, open the **FSI Importer**, select the file, click **Validate**, then **Import**.
5. The image link appears on the invoice's **Additional** tab in Foundation.

### 11.2 API-based export
Approved documents are queued and sent to the ERP. **Send to ERP** pushes them; the **Queue** popup
shows what is Pending and In Progress and lets you **Clear Queue**. Failed sends raise an error status
with the reason and are recorded in the audit trail.
**Auto Enqueue Documents** (Vista): approved documents are pushed to ERP processing automatically at
the end of the day, with no manual step.

### 11.3 Export batches (Downloads)
The **Downloads** tab lists export batches with Batch Name, Created At, Updated At, No. Documents,
Generated By and Status (Generated / Processing / Error / Downloaded / In ERP). You can **Download**
a batch again or **Regenerate** it, and open a batch to see the documents inside.

### 11.4 Foundation: Google Drive image sync
Invoice images reach Foundation through **Google Drive mirroring — not through Document Imaging**.

Setup:
- Create one dedicated Google account for Beiing Human and share the credentials with the team; no
  individual Google accounts and no extra Google licences are needed.
- Team members sign in to that account in the Google Drive desktop app.
- Every desktop needs the same local path: `C://BeiingHuman/Invoices`. It must stay a **local** folder;
  Google Drive handles the backup. Multiple Google accounts on one machine do not conflict.

If images are missing in Foundation:
1. Log in as AP Admin → **Profile**.
2. Use the manual sync feature.
3. Select the date range for the missing invoices → **Upload**.
Images sync from Google Drive to Foundation without overwriting documents that are already there.
Also verify the Google Drive configuration and the local folder path — that is the usual cause.

---

## 12. Reporting and search

### 12.1 INYA report (Invoices Not Yet Approved)
**To download:** go to the **Dashboard** tab and click the **INYA** button. The file downloads
immediately. (Tooltip in the app: "Download INYA (Invoices not yet approved) by approver".)

Columns:
- **A** — Vendor name
- **B** — Invoice number
- **C** — Invoice amount
- **D** — Number of required approvers
- **E** — List of approvers. `/` separates approvers at the same level; `=>` separates different levels.
- **F** — Current approver(s)
- **G** — Date assigned to the current approver
- **H** — Time assigned to the current approver

Use it to find where approvals are stuck.

### 12.2 Advanced Search
A dedicated search screen that searches across every status at once. Filters:
Document Number, keyword ("Includes the Words"), Vendor, Job Id, Cost Id, Cost Type, Phase, GL Account,
Purchase Order, Total, Document Date, Receipt Date, Due Date, Created At, Updated At, Status, Current
Owner, Category, Equipment Number, Service Code, Payment Status (Paid / Unpaid), Sort (Old to New /
New to Old).
Status options: Approved, Pending, On Hold, Error, Duplicate, Attached, Processing, In Review,
Rejected, In ERP, In Q&A.
**Search** runs the query, **Clear** resets every field.

**Finding delivery tickets that were approved but never attached to an invoice.** This is the one
thing the Documents tabs cannot do, and Advanced Search can:
1. Open **Advanced Search**.
2. Set **Document Type** to **Delivery Ticket**.
3. An extra **Status** filter appears (it is specific to delivery tickets) — choose **Unattached**.
   "All" applies no attachment filter.
4. **Search**.

**Finding everything sitting with one person.** Use the **Current Owner** filter to see the documents
a specific user is currently holding — useful for covering someone on leave.

### 12.3 Dashboard
Charts and metrics on the Dashboard tab: average approval time per document, average changes per
document, documents by vendor, by amount, by aging, total by aging, by Job ID, by Cost ID, by document
type, error vs success ratio, response time per document, and total documents. Filters apply to the
whole dashboard.

### 12.4 Downloading document data
You can download the **INYA report**, **export batch files (.csv / .txt)**, and per-document CSV/XML
from the documents list. There is no one-click "export every invoice ever processed into one
spreadsheet" button — for a full historical extract, contact support@beiinghuman.com and describe the
fields and date range you need.

---

## 13. Company Settings reference

Settings live under the dropdown next to your name → **Profile** (also called Settings). Changing them
requires the *Update Company Profile Settings* permission. Settings are grouped into four sections.

### 13.1 Duplicate & Validation
| Setting | What it does |
|---|---|
| **Duplicate Bill No Check** | Detects documents with the same bill number for the same vendor. |
| **Duplicate Detection on File Processing** | Detects a previously uploaded file so the same document is not processed twice. |
| **Coding Validations** *(Foundation, Vista)* | Validates coding for quality and ERP compliance. |
| **Validations for Last Approver Only** *(Vista)* | Coding validations apply only to the final approver, not every approver. |

### 13.2 Document Processing
| Setting | What it does |
|---|---|
| **Doc Splitter** | Splits multi-document PDFs into individual, categorized documents. |
| **Receipt Import** | Upload and manage expense receipts in the app. |
| **Quote and PO Import** *(Foundation, Vista, Spectrum)* | Upload quotes and purchase orders for reference and matching. |
| **Delivery Ticket Import** *(Foundation, Vista, Spectrum)* | Upload delivery tickets for receiving and invoicing. |
| **G702 Import** | Upload and manage G702 progress-billing documents. |
| **Consolidate Line items** | Combines line items into a single entry for cleaner matching. |
| **Line Items Total Matching** | Line item totals must match the document total. |
| **Line Items Amount Calculation** | Line amounts must match quantity × unit price. |
| **Miscellaneous Amount Calculation** *(Vista)* | Header total = sum of line amounts − miscellaneous amount. |
| **Transaction Date as Current Date** | Pre-fills the Transaction Date with today instead of the invoice date. |
| **GL Date as Current Date** *(Vista — same flag, Vista wording)* | Pre-fills the GL Date with the 1st of the current month instead of the invoice date. |
| **Display Tax as a Column** *(Vista, needs Tax Calculation)* | Shows tax as a per-line column instead of a separate tax row. |
| **Calculate Terms & Discounts in ERP** *(Vista)* | The ERP calculates due date, discount date and discount from payment terms. When off, Beiing Human auto-fills them from the selected payment term. |
| **Auto Enqueue Documents** *(Vista)* | Approved documents are pushed to ERP processing automatically at end of day. |
| **Vendor COI Compliance** | Shows each vendor's Certificate of Insurance compliance status on the documents list and the review screen. |
| **Sync data with Google Drive** *(Foundation + Google sign-in)* | Automatic Google Drive synchronization for document storage. |
| **Default Receipt Vendor** | Set default vendors for receipts; when on, pick the vendors from the list. |

### 13.3 Coding Rules
| Setting | What it does |
|---|---|
| **Cost Type, Job Id & Cost Id** | Enables job costing fields. Turn this on if you are a construction company. |
| **Phase** | Enables project phases. |
| **Purchase Order / Subcontract Matching** *(Foundation, Vista, Spectrum, RentalMan)* | Match invoices against POs/subcontracts to verify item, quantity and price. |
| **Default Coding** *(Foundation, Vista, Spectrum, RentalMan)* | Applies predefined vendor-based coding rules from the ERP. |
| **Job Budget based Coding** *(Foundation, Vista)* | Codes from the job budget. |
| **Job Budget Management** | PM-owned budgets with Budget vs Committed vs Actual tracking per job. |
| **Service Code and Equipment No** *(Foundation, Vista, Spectrum)* | Adds service codes and equipment numbers. |
| **AI Code Prediction** | AI-based coding suggestions and automation. |
| **Save Vendor Codes** | Saves the coding per vendor and pre-fills it next time. |
| **GL Division** *(Foundation, Spectrum)* | Enables GL divisions. |
| **Type Field** *(Vista)* | Adds a required Invoice Type field on Account Details and Line Items. |
| **Tax Calculation** *(Vista)* | Tax is calculated on the total; Tax Code / Tax Type become required. |
| **Payment Terms** | Documents carry a Payment Terms field. On by default. |
| **Real-Time Notifications** | Shows live notifications. When off, no notification is displayed and the app just refreshes data in the background. |

*Default Coding, AI Code Prediction and Job Budget based Coding are mutually exclusive — enabling one
disables the others.*

### 13.4 Approval Workflow
| Setting | What it does |
|---|---|
| **Manager as First Approver** | The manager approves first, then it goes to AP. |
| **Manager Content Editing** | Managers may modify document content. |
| **Confidence score based Pointing** | Colour-codes fields by AI confidence. |

### 13.5 Other settings on the Profile page
- **Work Order** *(Vista)* — enables Work Order for project tracking.
- **Approved Invoice Notification Days** — how many days a document may sit in Approved before a
  reminder is sent (e.g. 3 = notify when approved for 3+ days).
- **Document Assignment** — how documents are distributed to accountants: **Default** (every accountant
  sees everything), **Auto** (load-balanced automatically to the least-loaded accountant) or **Manual**
  (assigned by hand). This directly controls which documents each accountant sees.
  A separate setting chooses which users are allowed to assign documents to others.
- **Batch Type** *(Vista)* — Approved or Unapproved batches.
- **Bank Account Integration (Plaid)** — connect/disconnect a bank account for the receipt-nudge feature.
- **Company Email** — your company's document intake address; can be edited and validated.
- **Code Visibility**.
- **Document Configuration** — choose which custom fields appear on each document type (Invoice,
  Receipt, G702, Quote, Delivery Ticket, Purchase Order). Custom fields come from your ERP; if the list
  is empty, sync your integration first.
- **Statement Reconciliation** and **FAQ Maintenance** entries.

---

## 14. Code Visibility (restricting which GL accounts / cost ids / job ids a user can see)

**Yes — you can limit which codes specific users are allowed to use.** This is the **Code Visibility**
feature in Settings.

How it works: you create **visibility groups**. Each group has one or more **ranges** and a list of
**excluded users**. The users in a group cannot see or code to values inside that group's ranges.

- Three code types can be restricted: **GL Account**, **Cost Id** (Cost Code / Item on Vista and
  Spectrum) and **Job Id** (Project Id on Vista and Spectrum). Each has its own tab.
- Ranges are **inclusive** of both ends. `From` must not be greater than `To`.
- GL accounts are numeric. Cost ids and job ids may be alphanumeric (letters, digits and `. / _ -`).
- A group is only saved when it has at least one complete, correctly ordered range **and** at least one
  excluded user.
- Restriction is enforced when the code lists are built, so a restricted user simply never sees those
  codes in the dropdowns.

Example: restrict GL accounts 1000–1070 for the shop users, and they will not see those accounts when
coding.

---

## 15. Job budgets

With **Job Budget Management** enabled, project managers own budgets per job, tracked as
**Budget vs Committed vs Actual**. Budgets have a status of draft, active or archived. You can create a
budget, edit it, import one from a file, delete it, and raise **change orders** which are then approved.
On QuickBooks Desktop the Budgets tab appears in the top navigation and budgets can sync with QBD.
With **Job Budget based Coding** (Foundation, Vista), documents are coded from the job budget.

---

## 16. Attachments and supporting documents

Use the attachment screen to attach supporting documentation to a document:
- Check images after payment
- W-9 forms for new vendors
- Certificates of Insurance (COI)
- Any other backup

**Attaching a check that paid several invoices:** open the attachment screen, upload the scanned check
image, and associate it with each relevant invoice.
Video walkthrough: https://beiinghuman.com/check-attachment-video/

Supporting documents appear alongside the invoice on the review screen, with a line-item comparison
view (Description, Quantity, Amount, Received, Remaining, Status) and a switch between the invoice and
the line items.

---

## 17. Notifications and emails

- **Daily approver reminder** — a daily email summarising pending approvals and documents needing
  attention. For approver roles (Manager, C Level) the count is their own routed queue. For accountants
  it is the whole company queue, which can be larger than what the Documents screen shows them — see
  the note about the daily email over-counting for accountants.
- **Approved invoice reminder** — driven by *Approved Invoice Notification Days*.
- **Missing receipt nudge** — when a card transaction has no matching receipt.
- **Processing failure alert** — sent to your AP team with the document name and reason.
- **New user registration alert** — sent when a user completes registration.
- **In-app notifications** — the bell icon; controlled by the **Real-Time Notifications** setting. With
  it off, the app still refreshes data in the background but shows no pop-ups.

---

## 18. Mobile

There is a native **Beiing Human** app for iOS (iPhone and iPad) and Android. It is a companion to the
web app, not a replacement: it covers reviewing, coding, approving and capturing documents from the
field, while AP setup, matching, reporting and administration stay on the web.

Install it by searching the App Store or Google Play for "Beiing Human" (Android package
`com.beiinghuman.app`). The installed version is shown in small text at the bottom of the mobile
dashboard — ask for it when someone reports a mobile problem.

### 18.1 Signing in

Use the same email and password as the web app. There is no separate mobile account and no
self-registration in the app: a user must be invited by an admin and have completed registration on the
web first. The app stays signed in between launches — you only sign in again after tapping the logout
icon (top right of every screen) or after a session expires.

**"You do not have permission to login to this app."** The app is built for approvers, and the
**Accountant** and **AP Admin (Owner)** roles are blocked from signing in on mobile. Those users work in
the web app. Manager, C Level, Admin and Sub Admin sign in normally. This is by design, not a bug — do
not troubleshoot it as a password problem.

**"Login failed. Invalid credentials."** The email or password was rejected. Confirm the same
credentials work on the web app; if they work on web but not on mobile, escalate.

### 18.2 The mobile dashboard

The dashboard shows a count card per category: **Total Documents**, To Review, On Hold, Rejected,
Approved (includes Attached), In Q&A, Duplicate and Exported. Total Documents is the sum of To Review,
On Hold, Rejected, Approved, In Q&A and Duplicate — it does not include Exported.

Tapping a card with a count of zero shows "No documents found in this category" rather than opening an
empty list. Pull down to refresh the counts; they also refresh on their own when a document finishes
processing while the app is open.

### 18.3 Document lists

Each document appears as a card with the vendor, a document-type badge, Received At, the document
number and the total. Lists load nine at a time and load more as you scroll. Documents stored as
*Estimate* are shown as **Quote**.

**Why is there no Approve button on the To Review list?** Deliberate. Approving a pending document has
to go through the document screen so the coding and line-item validations run first and cannot be
skipped from the list. Tap **Details**, review, then approve there. Approve does appear directly on the
On Hold and Rejected lists.

**Can I search or filter on mobile?** No. Advanced Search, date and amount filters and sorting are
web-only. On mobile you navigate by status card from the dashboard.

### 18.4 The mobile document screen

The mobile equivalent of the Human Review screen, top to bottom: the document image (tap to open full
screen, swipe between pages, pinch to zoom), **Document Details** (header fields, vendor as a dropdown),
**Account Details** (the coding dropdowns, hidden for delivery tickets, which are not coded),
**Line Items**, and **Activity**. On a document that is In Q&A the Activity section moves to the top so
the open question is the first thing the approver sees.

Every line-item cell is editable; cells that map to an ERP code list render as dropdowns. Below the rows
are **Add Line Item**, **Reset** (restore the originally extracted values) and **Delete All**, plus a
trash icon per row. All of them confirm first.

**"I can't edit anything on this document."** Three causes: it was opened from the **Exported**
category (exported documents can never be re-coded, same as web); its status is Approved, In Q&A or
Duplicate; or the user is a Manager, is not the document's initial approver, and the company has not
granted managers the Manager Content Editing permission.

### 18.5 What each status allows on mobile

| Status | Available on mobile |
| --- | --- |
| To Review / Waiting For Approval | Approve (document screen only), Reject, On Hold, Comment, Details, Delete |
| On Hold | Approve, Reject, Question, Details, Delete |
| Rejected | Approve, Reject, On Hold, Question, Details, Delete |
| In Q&A | View & Reply, Back — locked until the question is resolved |
| Approved | Details, Back only |
| Duplicate | Proceed, Delete |
| Exported | Details only, read-only |

**Question** is not offered while a document is Waiting For Approval, matching the web app. A manager
acting as initial approver (no approvers assigned yet) sees only Approve, Comment, Details and Delete.

Delete is limited to the AP Admin, Accountant and Manager roles, and a Manager can only delete documents
they uploaded themselves. Since AP Admin and Accountant cannot sign in on mobile, Delete on the phone
means a manager's own uploads.

### 18.6 Approving, rejecting and holding

**"Fix N issues before approving."** The document has validation errors that must be corrected first.
The alert lists the first five, with "+N more" if there are others. Usual causes are missing or invalid
coding, a line-item amount that does not match quantity × unit price, and ERP-specific required fields.
There is deliberately **no "Approve Anyway" on mobile** — because every line-item cell is editable on
the phone, the approver can fix the problem in place and approve again. Validation is skipped for
earlier approvers when the company has ERP validations disabled, for manager initial-approver
hand-offs, and for Vista delivery tickets and quotes.

**Reject** always asks for a comment first; the comment is written to the Activity trail and then the
document is rejected. Rejecting without a comment is not possible on mobile. **On Hold** parks the
document for discussion. **Comment** adds a note without changing status. **Proceed**, on a Duplicate,
releases the document to continue through the workflow.

### 18.7 Q&A on mobile

Tap **Question** to raise one. The approver must type the question *and* pick at least one person to
assign it to — the submit button stays disabled until both are done. The document then moves to In Q&A
and is locked until resolved. Open it with **View & Reply**; the thread at the top offers **Reply** and,
where permitted, **Resolve**. Resolve is available to users with the same role as whoever raised the
question (AP Admin and Accountant can resolve each other's). Everything written on mobile appears in the
same Activity trail as the web app.

### 18.8 Uploading from a phone

If the user's role has the upload permission, the dashboard shows **Upload File**, offering **Receipt**,
**Quote** and **Delivery Ticket**, each via **Take a Picture** or **Choose from Gallery**. The app asks
for camera or photo-library permission the first time; declining produces "Camera permission is
required" or "Gallery permission is required" and has to be granted in the phone's own settings. After
upload the document goes through normal processing and approval.

Photographing a receipt is how credit card receipts enter Beiing Human — there is no direct import of
the receipt document itself from a bank or card provider.

**"I don't see the Upload File button."** The upload permission is not enabled on that user's role. An
admin enables it under Users → User Roles, and then the user must sign out of the app and back in.

### 18.9 Creating a PO on mobile

If the account has the PO/Quote permission the dashboard shows **Create PO**. It loads the vendor list
and units of measure from the ERP, the line total recalculates from quantity × unit price, and on submit
the app builds a PO PDF on the device and uploads it as a PO document.

**"Create PO is missing even though the permission was turned on."** The app reads permissions **at
sign-in only**. Sign out and back in and the button appears.

### 18.10 Mobile notifications and updates

While the app is open the user gets a live **"Document Ready"** banner when a document finishes
processing, and the dashboard counts refresh by themselves; the connection re-establishes when the app
returns to the foreground. The app does **not** send push notifications to a closed or backgrounded
app — the daily approver reminder email remains the offline nudge.

The app checks for a newer version on launch and on returning to the foreground. An optional update is a
dismissible prompt on iOS and a background Play Store download on Android. A required update shows a
full-screen **Update Required** screen that blocks the app until the user installs the new version from
the store.

### 18.11 Company settings and cached profiles

**When an admin changes a company setting, does everyone get it?** Yes. Saving Settings writes the
change to the company record *and* pushes the document-related permissions (Doc Splitter, Receipt
Import, Quote and PO Import, Delivery Ticket Import, G702, Duplicate Bill No Check, PO Matching,
Cost Type/Job Id/Cost Id, Consolidate Line Items, ERP type) to **every user who has completed
registration**. Users who were invited but have not registered yet pick the settings up from the
company record when they do register.

If a user still sees the old behaviour after that, their app is holding a cached profile — sign out and
back in to refresh it. This is the fix for most "my admin changed it but the app disagrees" reports,
because the mobile app reads permissions at sign-in.

### 18.12 What the mobile app cannot do

Advanced Search, filters and sorting; the INYA report, other reports and dashboard analytics; matching
an invoice to a PO or delivery ticket; the attachments screen (checks, W-9s, COIs); user management,
approval policies, company settings and ERP setup; document splitting and the Batch tab; the vendor
portal; and exporting to the ERP. All of these are web-app work.

**"Session expired. Please login again."** The authentication token could not be refreshed; signing in
again resolves it. If it repeats for the same user, escalate with their app version.

---

## 19. Vendor portal

Vendors get their own login and a restricted view: an **All Documents** tab showing only their own
documents, plus a vendor dashboard. Vendors cannot see other vendors' documents or company settings.

---

## 20. Troubleshooting

**First thing to try for anything that looks visually wrong or stale.** Beiing Human ships updates
frequently and the browser can hold on to the old version. Log out, then hard refresh —
**Ctrl + Shift + R** on Windows, **Cmd + Shift + R** on Mac — and try again. This is the fix for an
empty Classify/Split tab, a screen that will not finish loading, a field showing an old value, and
codes or payment terms that look wrong right after a release.

**Export blocked: "One or more invoices have a payment term that is not in your approved Foundation
terms list."** The payment term on the invoice does not exist in Foundation's payment terms list, so
the export is stopped before it can fail inside Foundation. Fix the term on the invoice (pull it back
first if it has already gone out for approval), then export again. If you cannot pull it back,
contact support — do not delete and re-upload, since that loses the approval history.

**"The AI put the wrong code on / left the coding blank."** Coding accuracy depends on which coding
mode is on. If it keeps guessing the wrong account for a vendor, turn on **Save Vendor
Codes** so the coding you used last time for that vendor is reused. Send a sample invoice to support
so the extraction can be tuned.

**"A receipt photographed on mobile creates far too many line items."** The AI reads every purchased
item as its own line. Turn on **Consolidate Line Items** in Settings, and new documents will default
to a single consolidated line. It applies going forward, not to documents already in the system.

**"Phases are not showing against the right jobs."** Turn **Default Coding** off and **Job Budget
based Coding** on, so phases and cost types are tied to the job. PO data (job, phase code, GL, cost
type) still pulls through normally with Job Budget based Coding on.

**"Beiing Human is pulling the wrong payment terms."** If your ERP vendor master already carries the
correct terms and you do not want the field in Beiing Human at all, an admin can switch the
**Payment Terms** setting off, which removes the field from the review screen.

**"New jobs / vendors / POs / equipment numbers are missing."** They arrive by sync, not instantly.
Run the sync from the Integration screen and re-check. If they still do not appear after a sync,
contact support.

**"My approval policy disappeared."** reconnecting the *same* ERP keeps the policy and only
re-enables it, but changing to a *different* ERP type deletes it. Also confirm the policy is still
marked **Active**.

**"Dates are flipped / month and day are swapped."** The system default format is **mm/dd/yyyy**.
Check the confidence colour on the date field, correct it by hand (human review always wins), and send
a problem invoice to support so the extraction can be analysed.

**"Images aren't showing in Foundation."** Beiing Human writes images through **Google Drive
mirroring, not Document Imaging**. Verify the Google Drive configuration and the local
`C://BeiingHuman/Invoices` path, then run the manual sync.

**"I can't unapprove an invoice."** Approved documents cannot be un-approved directly. If it has not
gone to the ERP yet, use **Pull Back** to recall it. Otherwise the workaround is to delete the approved
document and re-upload it through the workflow.

**"I need to delete many invoices at once."** Documents are deleted from the list, one selection at a
time; there is no company-wide bulk purge. Contact support if a large clean-up is needed.

**"A delivery ticket won't attach."** Check the three criteria — matching vendor, an invoice
number present, and a delivery ticket date on or before the invoice date.

**"A user can't see the Policy tab / the Users screen / the On Hold tab."** Those are role permissions:
*Update Policy*, *Update Users*, *On Hold Document*. Ask an AP Admin to edit the role under
**Users → User Roles**.

**"A setting is greyed out."** Most settings are ERP-specific or mutually exclusive with another
setting. Check the ERP notes and the mutually-exclusive pairs listed against each setting.

**"A user in the ERP isn't in Beiing Human."** Run **Sync Users** on the Users screen, then **Register**
them. Users who do not exist in the ERP are added with **Add User**.

**"Vista: GL Date is rejected."** The Vista GL Date must be the **first day of a month** and must fall
in an **open AP period**. The error message lists your company's open period window.

**"Vista: invoice number too long."** Vista allows up to 30 characters; other ERPs 20.
Foundation vendor names allow up to 150 characters; other ERPs 41. Foundation line descriptions are
capped at 30 characters.

---

## 21. Limits

These are the limits actually enforced by the platform:

| Limit | Value |
|---|---|
| Maximum file size (multi-page document) | 25 MB |
| Maximum file size (single page) | 10 MB |
| Documents per vendor through the vendor API | 150 by default, unless a higher per-vendor limit is configured |
| Invoice number length | 30 characters on Vista, 20 characters on other ERPs |
| Vendor name length | 150 characters on Foundation, 41 characters on other ERPs |
| Line description length (Foundation) | 30 characters |
| Purchase order number length | 10 characters |

**There is no enforced cap on the number of jobs, vendors, users, GL accounts or documents in a
company.** If a customer asks "is there a limit on the number of jobs" the answer is no — the system
does not impose one. Anything about *contractual* volume on their plan is a commercial question for
their account manager, not a product limit.

---

## 22. Vendor COI compliance and the COI Tracker

Certificate of Insurance tracking lives in two places: a **badge inside the main app**, and a
**separate COI Tracker application** where the actual work is done.

### 22.1 The COI compliance badge in the main app
Turn on **Vendor COI Compliance** in Settings → Document Processing. Each vendor's COI status then
appears as a coloured badge on the documents list and on the document review screen, so AP can see a
lapsed certificate while coding the invoice rather than finding out later.
Statuses: **Compliant** (green), **Expiring Soon** (amber), **Expired** (red), **Missing** (grey),
**Waived** (blue).

### 22.2 Opening the COI Tracker
Click the **shield icon** in the top navigation bar of the main app (tooltip: "COI Tracker"). It opens
**coi-tracker.beiinghuman.com** in a new tab and signs you in automatically using your existing
session — there is no second password, and the token is never put in the address bar. If the tab
opens but does not sign you in, close it and click the shield again; the handshake times out after
30 seconds.

### 22.3 The two status columns — read them separately
The dashboard grades every vendor on **two independent axes**. A current certificate can still be
underinsured, and an expired one may have had ample limits, so neither column alone means "compliant".

**Expiration status — is the certificate current?**
| Status | Meaning |
|---|---|
| **Compliant** | A certificate is on file and not near expiry |
| **Expiring Soon** | Expires within the next **30 days** |
| **Expired** | The expiration date has passed |
| **Missing** | No certificate on file with a usable date |
| **Waived** | The requirement has been waived for this vendor |

Status is driven by the certificate with the **latest** expiration date, so a renewal supersedes the
old one. It is also rolled up **per coverage** — an expired Workers' Comp makes the vendor read
Expired even if the General Liability is current.

**Limit status — is the policy big enough for the subcontract?**
Graded against your requirement template: **Meets**, **Deficient**, **Unknown**, or **No COI**.

### 22.4 Why a vendor reads "Unknown" instead of "Deficient"
This is deliberate and is the most common question about the dashboard. **A red "Deficient" chip only
appears when a number was actually read and compared** — because that chip gets forwarded to the
sub's insurance agent, and accusing a sub of carrying too little insurance when the certificate was
simply unreadable is expensive. So:
- A limit that could not be read is **Unknown**, never a failure.
- A coverage with **no certificate on file** reads as **Not Provided** — unverified, not failed. You
  know you do not *hold* it; you do not know the sub does not *carry* it.
- A lumped `"GL, Auto, WC"` line proves the coverage exists, but its single limit cannot be attributed
  to each coverage, so those read **Unknown**.
- A **WC Exempt Form** (the state exemption sole proprietors file) is **Exempt**, not a failure.

### 22.5 Which vendors are tracked
By default the tracker follows **vendors on active jobs** — taken from your ERP's jobs, subcontracts
and purchase orders — not your entire vendor book. Chasing a certificate from a sub who finished two
years ago is noise.

You can switch this on the dashboard between **Active jobs** (default) and **All vendors**.

**"Why is a vendor missing from the list?"** Most often they are not on an active job. Switch the
scope to All vendors to confirm. If your jobs and subcontracts have never been synced from the ERP,
the tracker cannot tell "nobody is on a job" from "no job data", so it deliberately falls back to
showing the **full** vendor book rather than showing you an empty screen.

### 22.6 Not chasing a vendor
Some vendors should never be chased — a utility, a government body, a supplier who carries no
subcontract. Click **Don't track** on that vendor's row. They are hidden from the default dashboard
and skipped by all automated outreach. The button becomes **Track** if you want them back.

### 22.7 Getting certificates in
Three ways:
1. **Upload it yourself** on the dashboard. The certificate is read automatically — ACORD 25 forms are
   extracted by AI — and you can correct or enter details by hand if anything is unreadable.
2. **Have the vendor upload it.** They receive a link to a **no-login upload page**; no account, no
   password. This is the answer to "how do I get COIs from my subs?"
3. **Automated renewal outreach** (below) sends that same link on a schedule.

### 22.8 Automated renewal outreach
As a certificate approaches expiry the tracker emails the vendor a no-login upload link at
**60, 30, 14 and 7 days**. Each threshold sends once per certificate cycle, and a renewal resets the
sequence, so nobody is emailed repeatedly about a certificate they already replaced. There is also a
manual "send now" for chasing one vendor immediately.

Two things worth telling customers:
- **The email is branded with your company, not with Beiing Human.** It arrives from
  `coi@documents.beiinghuman.com`, an address the sub has never seen, so it carries the customer's
  name — otherwise it reads as phishing and gets ignored.
- **Outreach is grouped by insurance agency, not by vendor.** A sub often buys auto from one agency
  and GL/WC from another; neither agency can act on the other's policy. So each agency receives its
  own email naming only the policies it issued.

### 22.9 Endorsements — Asserted vs Verified
The ADDL INSD / SUBR WVD boxes on an ACORD 25 only record that the notation was **requested**, so a
ticked box reads as **Asserted**. It becomes **Verified** when the matching endorsement form
(CG 20 10, CG 20 37, CG 24 04, CG 20 01) is uploaded as an Endorsement document. Removing that form
demotes it again. Unknown never counts as denied, and never fails a vendor.

---

## 23. Names that sound like features but are not available

If a user asks about any of the following **by name**, say plainly that it is not something Beiing
Human offers today, and point them at the nearest thing that does exist. Do **not** quietly answer
about the similarly-named feature as though they are the same thing — the user asked about a specific
capability and needs to know it is not there.

| Asked about | The honest answer |
|---|---|
| **PO Receipt Matching** / matching an invoice to individual **PO receipts** / receipt-level matching | Not available. Invoices are matched to a purchase order **as a whole**, not to the individual receipts recorded against it. The nearest thing is Match → Purchase Order, whose PO view shows Amount, Received and Remaining per line so you can see what is still open. |
| **Bulk / batch delete** of documents | Not available. Documents are deleted from the list a selection at a time; there is no company-wide purge. |
| **Un-approving** an already approved document | Not available directly. Pull Back works only before it reaches the ERP. |
| **Exporting every invoice** to one spreadsheet | Not available as a self-service button. INYA and export batches are the built-in downloads. |
| **Foundation division (Level 1 / Level 2) sync** | Not available yet. GL Division exists as a coding field on Foundation and Spectrum, but job divisions do not sync from Foundation. |
| **Lien waiver tracking** | Not part of the product today. |

If a requested capability is not in this document at all, treat it as unavailable rather than
assuming it exists under another name.

---

## 24. Questions this document deliberately does not answer

If a user asks any of the following, do **not** guess — say it needs a human and route to
**support@beiinghuman.com** (include the user's email and company):

- Pricing, invoicing, contract or billing questions, including contracted document volumes
- Requests for a full historical export of every invoice into Excel
- Anything about their specific data ("why is *this* invoice missing", "why did *this* fail")
- Requests for a new feature or a change to how the ERP integration behaves
- Security, SOC 2, data-retention and compliance questions

---

*Maintained by Beiing Human. When a feature ships or a setting is renamed, update this document —
the chatbot answers only from what is written here.*
