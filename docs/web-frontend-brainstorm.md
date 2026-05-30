# Web Frontend — Feature Brainstorm

> Status: **brainstorm / idea backlog**. Created 2026-05-30.
> No decisions, no implementation — this is a menu of what the website *could*
> become now that the typed pipe (TanStack Query → openapi-fetch → FastAPI) is
> proven and only `/stats/overview` is wired up.
>
> Companion to [`web-frontend-stack.md`](web-frontend-stack.md). Every idea
> below is annotated with the endpoints it leans on and whether today's API
> already supports it (✅), needs only client-side work (🟡), or would need a
> **new/extended endpoint** (🔴).

## 0. What we have to work with

The archive is a stream of **BLE observations** — each a `(scanner_id,
observed_at_utc, address, rssi, name, local_name, service_uuids,
manufacturer_data)` row. Two kinds of monitor feed it:

- a **LAN monitor** the Fetcher Hub pulls continuously, and
- a **BT-only monitor** a drive-by laptop syncs opportunistically.

So every device the website shows is "a Bluetooth thing that physically passed
near one of our sensors." That framing — *presence over time and space* — is
the spine of every idea here.

The endpoints currently available (all read-only):

| Endpoint | Gives us |
| --- | --- |
| `/stats/overview` | global totals + time range (already used) |
| `/stats/hourly` | per-scanner, per-hour `observations` + `distinct_addresses` |
| `/stats/vendors` | per-manufacturer `observations` + `distinct_addresses` |
| `/scanners`, `/scanners/{id}` | per-monitor totals, first/last seen, recent ingests |
| `/addresses` | paginated devices; filter by `q`, `scanner_id`, `seen_since`; sort by last/first seen or count |
| `/addresses/{addr}` | one device's summary incl. `scanners[]`, `vendors[]`, `services[]` |
| `/addresses/{addr}/observations` | one device's full timeline (incl. `rssi`) |
| `/observations` | recent raw observations across everything |
| `/search` | unified search over address/name/vendor/service |

Three response fields do most of the heavy lifting for the "interesting"
questions the user asked about:

- **`first_observed_utc` / `last_observed_utc`** on every address → "new" and
  "gone quiet" devices.
- **`scanners[]`** on every address → "seen by both monitors."
- **`hour_utc` buckets** → everything time-series and graphically impressive.

---

## 1. The questions a home-security user actually asks

Framing the features as the user's real questions keeps us honest about value:

1. **"Is anything *new* hanging around my house?"** — devices first seen
   recently. Possible casing of a property, a neighbour's new gadget, a tracker.
2. **"Did a regular visitor stop showing up?"** — devices that *were* frequent
   but have gone quiet. Could be benign, could mean a sensor died.
3. **"What's been seen by *both* monitors?"** — a device observed at two
   physical vantage points is moving through/around the property, not just
   sitting in one room. Higher signal.
4. **"Who's here *right now*, and who's always here?"** — the persistent
   baseline (my own devices, the neighbour's fridge) vs. transient passers-by.
5. **"Is the system itself healthy?"** — are both monitors still ingesting? When
   did the BT-only monitor last sync?
6. **"Show me something I wouldn't have noticed."** — anomalies, patterns,
   rhythms in the data.

The sections below map features onto these.

---

## 2. "New devices" feed — Q1

**The single highest-value view for a security use case.** A reverse-chronological
feed of devices whose `first_observed_utc` is recent.

- **Data:** `/addresses?sort=first_seen` ✅ — already sorts by first-seen
  descending. Each card shows address, best-known name/`local_name`, vendor(s),
  which scanner(s) caught it first, and "first seen 3h ago."
- **Graphically:** a **timeline / swimlane** of first-appearances over the last
  7/30 days; a daily "new device count" bar so a spike (lots of new MACs at once)
  jumps out.
- **Security smarts (client-side, 🟡):**
  - **MAC randomization awareness.** Modern phones rotate private MACs, so a
    flood of one-shot addresses is normal noise. Flag instead the devices that
    are *new* **and** *sticky* (first seen recently **but** already many
    `observations` / seen across several hours) — those are the ones that came
    and *stayed*.
  - **"New and near" ranking** — combine recency with strong `rssi` (close to the
    sensor) to surface a new device that's physically close.
- **Nice extension (🔴):** a `first_observed_since` filter on `/addresses` would
  let the server do the "new in last 24h" cut instead of the client.

---

## 3. "Gone quiet" / dormant devices — Q2

The inverse, and just as interesting: devices that *used to* be regular and
have **not** been seen in a long time.

- **Data:** `/addresses?sort=last_seen` ascending gets the stalest devices ✅,
  but the truly interesting set is **"high lifetime `observations`, but
  `last_observed_utc` is old"** — a device that was around a lot and then
  vanished. That ranking is client-side over a fetched page 🟡 (or a 🔴 server
  sort like `sort=dormancy`).
- **Graphically:** a **"recency vs. frequency" scatter** — x = days since last
  seen, y = total observations (log). Your own always-on devices cluster
  top-left; the dramatic top-**right** points are "was very present, now gone,"
  which is exactly what a human should glance at.
- **Why it matters:** a regular visitor's tracker disappearing is benign; *your
  own* monitor going dark (a whole cohort of devices going quiet at once) means
  a **sensor outage**, which ties into §7 health.

---

## 4. "Seen by both monitors" — Q3

A device in an address's `scanners[]` array with **length ≥ 2** has been
observed from two physical vantage points. For a two-monitor deployment this is
a strong, cheap signal of movement/coverage overlap.

- **Data:** `/addresses` returns `scanners[]` per device ✅ — filter client-side
  for `scanners.length >= 2` 🟡. (A 🔴 `min_scanners=2` query param would make
  this a first-class server filter.)
- **Views:**
  - **A dedicated "Multi-monitor devices" list** — the devices both monitors
    agree on. These are the most "real" / persistent presences.
  - **Venn / overlap diagram:** three numbers — seen only by monitor A, only by
    B, by both — rendered as a proportional Venn or a simple stacked bar. Instantly
    answers "how much do my two sensors' worlds overlap?"
  - **Hand-off timeline for one device:** on the device-detail page, plot its
    observations colour-coded by `scanner_id` (from `/addresses/{addr}/
    observations`, which carries `scanner_id` per row ✅). You can *see* a device
    move from monitor A's coverage into monitor B's — a literal track.
- **Security angle:** something seen by **both** a fixed indoor LAN monitor and
  the roaming BT-only monitor is circulating around the property, not parked in
  one spot. Worth a distinct badge.

---

## 5. The graphically impressive centrepiece — Q4/Q6

This is where Observable Plot earns its place. Ideas ranked roughly by
"wow per unit of effort."

### 5a. Activity heatmap (hour × day) — **top pick** 🟡
A GitHub-contributions-style grid: **day of week × hour of day**, cell shade =
observation volume. Built straight from `/stats/hourly` ✅ by re-bucketing the
hourly rows. Reveals the *rhythm* of the area at a glance — quiet 3am, busy
commute hours, a weekend pattern. One anomalous hot cell at an odd hour is
visually obvious. Cheap, dense, and genuinely beautiful.

### 5b. Streamgraph / stacked area of activity over time 🟡
`/stats/hourly` gives `observations` per `scanner_id` per `hour_utc`. Stack the
two monitors as bands over time → a flowing streamgraph showing total ambient
BLE activity and each monitor's share. A gap in one band = that monitor stopped
reporting (health signal, again).

### 5c. "Devices present" ribbon vs. raw observations 🟡
Plot `distinct_addresses` per hour alongside `observations` per hour (both in
`/stats/hourly`). Divergence is interesting: *many observations, few devices* =
a few chatty devices; *many devices, few observations each* = lots of
passers-by. A nice dual-line chart.

### 5d. Vendor treemap / bar race 🟡
`/stats/vendors` ✅ → a treemap of the BLE ecosystem around the house (Apple,
Samsung, Google, tracker vendors, "(unknown)"). Visually rich and instantly
legible. A treemap of `distinct_addresses` (not observations) better reflects
"how many distinct things of each brand."

### 5e. Per-device RSSI sparkline / proximity chart 🟡
`/addresses/{addr}/observations` carries `rssi` per observation ✅. On the
device-detail page, a small-multiple of RSSI over time reads as a **proximity
trace** — you can see a device approach (rising RSSI) and leave. Colour points
by `scanner_id` to combine with §4's hand-off idea.

### 5f. Vendor "first appearance" timeline 🟡
A horizontal timeline where each vendor's band starts at the first time we ever
saw that manufacturer. Storytelling for "the BLE landscape of my street, over
time."

> Note: 5a–5d all run off the two `/stats/*` endpoints we *already have* — so
> the most impressive visuals are also the lowest-effort. Good news.

---

## 6. Device explorer & search — the workhorse — Q1/Q4

Less flashy but the daily-driver view, and the natural home for drill-downs.

- **Devices table** off `/addresses` with cursor pagination ✅: columns for
  name/address, vendor, # scanners, observations, first/last seen, a tiny
  inline activity sparkline. Sortable via the existing `sort` param.
- **Search bar** off `/search` ✅ — unified across address/name/vendor/service,
  with `kind` badges on results. This is the entry point to everything.
- **Device detail page** off `/addresses/{addr}` + `/addresses/{addr}/
  observations` ✅: the summary header, the RSSI/proximity chart (5e), the
  scanner hand-off timeline (§4), and a raw observation log with pagination.
- **Saved filters / watchlist (🔴 or local-storage 🟡):** let the user "pin" a
  device (e.g. an unknown one that showed up) and get it surfaced on the
  overview. Could be purely client-side (localStorage of addresses) to start.

---

## 7. System health & monitor status — Q5

A security system you don't trust is worthless, so make its own liveness
first-class.

- **Data:** `/health` ✅ (archive freshness, `last_ingest_at_utc`),
  `/scanners` ✅ (per-monitor `last_observed_utc`), and
  `/scanners/{id}` ✅ (`recent_ingests[]` with `rows_inserted`/`rows_skipped`/
  `pi_package_version`).
- **Views:**
  - **Monitor status cards:** each monitor green/amber/red by how long since its
    `last_observed_utc`. The **BT-only monitor** is expected to be bursty (synced
    by drive-by), so its "healthy" threshold should differ from the LAN
    monitor's — a nice product detail.
  - **Ingest history sparkline** per monitor from `recent_ingests[]` — bar per
    snapshot, height = `rows_inserted`, so a flatlining monitor is obvious.
  - **"Data freshness" banner** site-wide from `/health.last_ingest_at_utc`.
  - **Version drift:** show `pi_package_version` per monitor so a stale Pi stands
    out.

---

## 8. Cross-cutting / "show me something" ideas — Q6

Higher-concept, mostly needing a little client-side cleverness (🟡) or modest
API help (🔴):

- **Co-occurrence / "travels together":** devices whose observation timestamps
  consistently cluster together likely belong to one person (phone + watch +
  earbuds + car). Derivable client-side by correlating `/observations` timelines
  🟡; expensive but striking as a force-directed graph. A 🔴 server endpoint
  would make it practical at scale.
- **Dwell-time distribution:** per device, `last_observed_utc -
  first_observed_utc` and observation density → "passers-by" (seconds) vs.
  "residents" (always). A histogram that cleanly separates the two populations.
- **Anomaly callouts:** simple rules over `/stats/hourly` — "3× the usual
  distinct devices for this hour-of-week" → a highlighted card. No ML needed,
  just a rolling baseline computed client-side 🟡.
- **Identity-stitching note:** acknowledge MAC randomization openly in the UI
  (a tooltip), and prefer stable signals (`name`, `local_name`, persistent
  vendor+service fingerprints) when presenting "a device." Manages user
  expectations and is itself an interesting design surface.
- **Map-less spatial intuition:** with only two monitors we can't triangulate,
  but a simple **A↔B presence matrix** over time (who's where, when) gives a
  pseudo-spatial read without GPS.

---

## 9. Endpoint coverage scorecard

How well today's API serves the ideas — useful for prioritising and for a future
API wishlist.

| Endpoint | Used today | Ideas it unlocks |
| --- | --- | --- |
| `/stats/overview` | ✅ wired | overview cards (done) |
| `/stats/hourly` | ❌ | heatmap 5a, streamgraph 5b, present-ribbon 5c, anomalies §8 |
| `/stats/vendors` | ❌ | treemap 5d, vendor timeline 5f |
| `/addresses` | ❌ | new feed §2, dormant §3, both-monitors §4, explorer §6 |
| `/addresses/{addr}` | ❌ | device detail §6 |
| `/addresses/{addr}/observations` | ❌ | RSSI/proximity 5e, hand-off timeline §4 |
| `/scanners` + `/{id}` | ❌ | monitor health §7 |
| `/observations` | ❌ | live recent feed, co-occurrence §8 |
| `/search` | ❌ | search bar §6 |
| `/health` | ❌ | freshness banner §7 |

**Takeaway:** *every* endpoint has an obvious, high-value home. Nothing is
orphaned. The two `/stats/*` endpoints alone unlock the most graphically
impressive views.

### Small API extensions worth considering later (🔴)
None are blockers — all have client-side fallbacks — but each would be a clean win:

1. `first_observed_since` filter on `/addresses` → server-side "new in last 24h."
2. `min_scanners` filter on `/addresses` → first-class "seen by both monitors."
3. A `sort=dormancy` (high observations, old last-seen) → the §3 dormant view.
4. A daily-bucket variant of `/stats/hourly` (or a `bucket=day` param) → cheaper
   long-range trend charts without pulling 720 hourly rows.

---

## 10. Suggested build order (for when we leave brainstorm mode)

Optimising for **value × low effort**, and for showing something impressive fast:

1. **Activity heatmap (5a)** + **streamgraph (5b)** on the overview — pure
   `/stats/hourly`, maximal wow, no new pages. Turns the static overview into a
   living dashboard.
2. **Device explorer + search (§6)** — the navigational backbone everything else
   links into.
3. **"New devices" feed (§2)** — the headline security feature.
4. **Device detail with RSSI + scanner hand-off (§4, 5e)** — the drill-down
   payoff.
5. **Monitor health (§7)** — trust in the system.
6. **Vendor treemap (5d)**, **dormant devices (§3)**, then the §8 high-concept
   experiments.

> Everything in steps 1–5 is buildable on **today's** API with zero backend
> changes. The 🔴 extensions in §9 are polish, not prerequisites.
