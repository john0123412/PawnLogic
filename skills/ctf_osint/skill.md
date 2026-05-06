---
name: ctf-osint
description: OSINT for CTF: social media tracking (X/Tumblr/BlueSky/Discord), username enumeration, reverse image search, geolocation (EXIF/MGRS/Plus Codes/What3Words), DNS/WHOIS, Wayback, FEC/Tor/GitHub mining.
license: MIT
compatibility: Requires filesystem-based agent (Claude Code or similar) with bash, Python 3, and internet access for OSINT lookups.
allowed-tools: Bash Read Write Edit Glob Grep Task WebFetch WebSearch
metadata:
  user-invocable: "false"
---

# CTF OSINT

Quick reference for OSINT CTF challenges. Each technique has a one-liner here; see supporting files for full details.

## Additional Resources

- [social-media.md](social-media.md) - Twitter/X (user IDs, Snowflake timestamps, Nitter, memory.lol, Wayback CDX), Tumblr (blog checks, post JSON, avatars), BlueSky search + API, Unicode homoglyph steganography, Discord API, username OSINT (namechk, whatsmyname, Osint Industries), username metadata mining (postal codes), platform false positives, multi-platform chains, Strava fitness route OSINT
- [geolocation-and-media.md](geolocation-and-media.md) - Image analysis, reverse image search (including Baidu for China), Google Lens cropped region search, reflected/mirrored text reading, geolocation techniques (railroad signs, infrastructure maps, MGRS), Google Plus Codes, EXIF/metadata, hardware identification, newspaper archives, IP geolocation, Google Street View panorama matching, What3Words micro-landmark matching, Google Maps crowd-sourced photo verification, Overpass Turbo spatial queries
- [web-and-dns.md](web-and-dns.md) - Google dorking (including TBS image filters), Google Docs/Sheets enumeration, DNS recon (TXT, zone transfers), Wayback Machine, FEC research, Tor relay lookups, GitHub repository analysis, Telegram bot investigation, WHOIS investigation (reverse WHOIS, historical WHOIS, IP/ASN lookup)

---

## Pattern Recognition Index

Dispatch on the **kind of clue** in the prompt/image, not on the story.

| Signal | Technique → file |
|---|---|
| Only a username / handle given | Username OSINT (namechk, whatsmyname, Osint Industries) → social-media.md |
| Twitter/X profile URL, numeric user ID, or snowflake-looking timestamp | Snowflake decode + Nitter + memory.lol → social-media.md |
| Tumblr blog name, Mastodon/BlueSky handle | Platform-specific JSON/API lookups → social-media.md |
| Unicode-rich post text (Cyrillic or mathematical letters in ASCII-looking words) | Homoglyph steganography → social-media.md |
| Image with distinct building, sign, mountain, or road layout | Reverse image + Google Lens / Baidu → geolocation-and-media.md |
| Railroad/road sign text, mileage markers, regional infrastructure | Geolocation via infrastructure maps + MGRS → geolocation-and-media.md |
| `WxYyyy` style or three-random-words string | Google Plus Codes / What3Words → geolocation-and-media.md |
| EXIF present with GPS / camera serial | ExifTool + metadata chain → geolocation-and-media.md |
| Target is a domain / host IP | WHOIS + reverse DNS + ASN → web-and-dns.md |
| Tor `.onion` address or relay fingerprint | Tor relay lookups + Wayback of hidden services → web-and-dns.md |
| GitHub org/user URL, or leaked GitHub token | GitHub repo analysis + commit mining → web-and-dns.md |
| FEC / SEC / public-record style clue (US political or financial) | FEC research → web-and-dns.md |
| Cryptocurrency address + transaction context | On-chain tx tracing → (see ctf-forensics/disk-and-memory.md cross-ref) |
| Strava / fitness route image | Route OSINT via Strava heatmap → social-media.md |

Recognize the **kind of artefact**; don't chase the story's names.

---

---

For inline snippets and quick-reference tables, see [quickref.md](quickref.md). The Pattern Recognition Index above is the dispatch table — always consult it first.



---

<!-- Source: geolocation-and-media.md -->

# Geolocation and Media Analysis

## Table of Contents

- [Image Analysis](#image-analysis)
- [Reverse Image Search](#reverse-image-search)
- [Geolocation Techniques](#geolocation-techniques)
- [MGRS (Military Grid Reference System)](#mgrs-military-grid-reference-system)
- [Google Plus Codes / Open Location Codes (MidnightCTF 2026)](#google-plus-codes--open-location-codes-midnightctf-2026)
- [Metadata Extraction](#metadata-extraction)
- [Hardware/Product Identification](#hardwareproduct-identification)
- [Newspaper Archives and Historical Research](#newspaper-archives-and-historical-research)
- [Google Street View Panorama Matching (EHAX 2026)](#google-street-view-panorama-matching-ehax-2026)
- [Road Sign Language and Driving Side Analysis (EHAX 2026)](#road-sign-language-and-driving-side-analysis-ehax-2026)
- [Post-Soviet Architecture and Brand Identification (EHAX 2026)](#post-soviet-architecture-and-brand-identification-ehax-2026)
- [IP Geolocation and Attribution](#ip-geolocation-and-attribution)
- [Google Lens Cropped Region Search (UTCTF 2026)](#google-lens-cropped-region-search-utctf-2026)
- [Reflected and Mirrored Text Reading (UTCTF 2026)](#reflected-and-mirrored-text-reading-utctf-2026)
- [What3Words (W3W) Geolocation (UTCTF 2026)](#what3words-w3w-geolocation-utctf-2026)
- [Monumental Letters / Letreiro Identification (UTCTF 2026)](#monumental-letters--letreiro-identification-utctf-2026)
- [Google Maps Crowd-Sourced Photo Verification (MidnightCTF 2026)](#google-maps-crowd-sourced-photo-verification-midnightctf-2026)
- [Overpass Turbo Spatial Queries (LAB'OSINT 2025)](#overpass-turbo-spatial-queries-labosint-2025)

---

## Image Analysis

- Discord avatars: Screenshot and reverse image search
- Identify objects in images (weapons, equipment) -> find character/faction
- No EXIF? Use visual features (buildings, signs, landmarks)
- **Visual steganography**: Flags hidden as tiny/low-contrast text in images (not binary stego)
  - Always view images at full resolution and check ALL corners/edges
  - Black-on-dark or white-on-light text, progressively smaller fonts
  - Profile pictures/avatars are common hiding spots
- **Twitter strips EXIF** on upload - don't waste time on stego for Twitter-served images
- **Tumblr preserves more metadata** in avatars than in post images

## Reverse Image Search

- Google Lens (crop to specific region, best for identifying landmarks/shops/signs)
- Google Images (most comprehensive)
- TinEye (exact match)
- Yandex (good for faces, Eastern Europe)
- Baidu Images / `graph.baidu.com` (best for Chinese locations — use when visual cues suggest China: blue license plates, simplified Chinese text, menlou gate architecture)
- Bing Visual Search

## Geolocation Techniques

- Railroad crossing signs: white X with red border = Canada
- Use infrastructure maps:
  - [Open Infrastructure Map](https://openinframap.org) - power lines
  - [OpenRailwayMap](https://www.openrailwaymap.org/) - rail tracks
  - High-voltage transmission line maps
- Process of elimination: narrow by country first, then region
- Cross-reference multiple features (rail + power lines + mountains)
- MGRS coordinates: grid-based military system (e.g., "4V FH 246 677") -> convert online

## MGRS (Military Grid Reference System)

**Pattern (On The Grid):** Encoded coordinates like "4V FH 246 677".

**Identification:** Challenge title mentions "grid", code format matches MGRS pattern.

**Conversion:** Use online MGRS converter -> lat/long -> Google Maps for location name.

## Google Plus Codes / Open Location Codes (MidnightCTF 2026)

**Pattern (Chine Zhao):** Flag format requires a Google Plus Code (e.g., `H9G2+47X`) instead of coordinates or W3W. Plus Codes are Google's open-source alternative to street addresses.

**Format:** `XXXX+XX` (short/local) or `8FVC9G8F+6W` (full/global). Characters from the set `23456789CFGHJMPQRVWX`. The `+` separator is always present.

**Generating a Plus Code:**
1. Find the exact location on Google Maps
2. Click the map to drop a pin at the precise spot
3. The Plus Code appears in the location details panel (e.g., `H9G2+47X Handan, Hebei, China`)
4. Or enter coordinates in the Google Maps search bar — the Plus Code shows in results

**Precision:** Standard Plus Codes resolve to ~14m x 14m areas (vs. W3W's 3m x 3m). Adding extra characters increases precision. Meter-level position changes can alter the code.

**Key insight:** Unlike W3W (proprietary, requires API key), Plus Codes are free and built into Google Maps. When a flag format shows `{XXXX+XXX}`, recognize it as a Plus Code. Position the Street View camera at the exact photo capture location, then read the Plus Code from the map pin.

**Reference:** https://maps.google.com/pluscodes/

---

## Metadata Extraction

```bash
exiftool image.jpg           # EXIF data
pdfinfo document.pdf         # PDF metadata
mediainfo video.mp4          # Video metadata
```

## Hardware/Product Identification

**Pattern (Computneter, VuwCTF 2025):** Battery specifications -> manufacturer identification. Cross-reference specs (voltage, capacity, form factor) with manufacturer databases.

## Newspaper Archives and Historical Research

- Scout Life magazine archive: https://scoutlife.org/wayback/
- Library of Congress: https://www.loc.gov/ (newspaper search)
- Use advanced search with date ranges

**Pattern (It's News, VuwCTF 2025):** Combine newspaper archive date search with EXIF GPS coordinates for location-specific identification.

**Tools:** Library of Congress newspaper archive, Google Maps for GPS coordinate lookup.

## Google Street View Panorama Matching (EHAX 2026)

**Pattern (amnothappyanymore):** Challenge image is a cropped section of a Google Street View panorama. Must identify the exact panorama ID and coordinates.

**Approach:**
1. **Extract visual features:** Identify distinctive landmarks (road type, vehicles, containers, mountain shapes, building styles, vegetation)
2. **Narrow the region:** Use visual clues to identify country/region (e.g., Greenland landscape, specific road infrastructure)
3. **Compile candidate panoramas:** Use Google Street View coverage maps to find panoramas in the identified region
4. **Feature matching:** Compare challenge image features against candidate panoramas:
   ```python
   import cv2
   import numpy as np

   # Load challenge image and candidate panorama
   challenge = cv2.imread('challenge.jpg')
   candidate = cv2.imread('panorama.jpg')

   # ORB feature detection and matching
   orb = cv2.ORB_create(nfeatures=5000)
   kp1, des1 = orb.detectAndCompute(challenge, None)
   kp2, des2 = orb.detectAndCompute(candidate, None)

   bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
   matches = bf.match(des1, des2)
   score = sum(1 for m in matches if m.distance < 50)
   ```
5. **Ranking systems:** Use multiple scoring methods (global feature match, local patch comparison, color histogram analysis) and combine rankings
6. **API submission:** Submit panorama ID with coordinates in required format (e.g., `lat/lng/sessionId/nonce`)

**Google Street View API patterns:**
```python
# Street View metadata API (check if coverage exists)
# GET https://maps.googleapis.com/maps/api/streetview/metadata?location=LAT,LNG&key=KEY

# Street View image API
# GET https://maps.googleapis.com/maps/api/streetview?size=640x480&location=LAT,LNG&heading=90&key=KEY

# Panorama ID from page source (parsed from JavaScript):
# Look for panoId in page data structures
```

**Key insights:**
- Challenge images are often crops of panoramas — the crop region may not include horizon or sky, making geolocation harder
- Distinctive elements: road surface type, vehicle makes, signage language, utility poles, container colors
- Greenland, Iceland, Faroe Islands have limited Street View coverage — enumerate all panoramas in the region
- Image similarity ranking with multiple metrics (feature matching + color analysis + patch comparison) is more robust than any single method

---

## Road Sign Language and Driving Side Analysis (EHAX 2026)

**Pattern (date_spot):** Street view image of a coastal location. Identify exact coordinates from road infrastructure.

**Systematic approach:**
1. **Driving side:** Left-hand traffic → right-hand drive countries (Japan, UK, Australia, etc.)
2. **Sign language/script:** Kanji → Japan; Cyrillic → Russia/CIS; Arabic → Middle East/North Africa
3. **Road sign style:** Blue directional signs with white text and route numbers → Japanese expressways
4. **Sign OCR:** Extract text from directional signs to identify town/city names and route designations
5. **Route tracing:** Search identified route number + town names to find the road corridor
6. **Terrain matching:** Match coastline, harbors, lighthouses, bridges against satellite view

**Japanese infrastructure clues:**
- Blue highway signs with white Kanji + route numbers (e.g., E59)
- Distinctive guardrail style (galvanized steel, wavy profile)
- Concrete seawalls on coastal roads
- Small fishing harbors with white lighthouse structures

**General country identification shortcuts:**
| Feature | Country/Region |
|---------|---------------|
| Kanji + blue highway signs | Japan |
| Cyrillic + wide boulevards | Russia/CIS |
| White X-shape crossing signs | Canada |
| Yellow diamond warning signs | USA/Canada |
| Green autobahn signs | Germany |
| Brown tourist signs | France |
| Bollards with red reflectors | Netherlands |

---

## Post-Soviet Architecture and Brand Identification (EHAX 2026)

**Pattern (idinahui):** Coastal parking lot image. Identify location from architectural style, vehicle types, signage, and local brands.

**Recognition chain:**
1. **Architecture:** Brutalist concrete buildings → post-Soviet region
2. **Vehicles:** Reverse image search vehicle models to narrow to Russian/CIS market cars
3. **Script:** Cyrillic signage confirms Russian-language region
4. **Flags:** Regional government flags alongside national tricolor → identify specific federal subject
5. **Brands:** Named restaurants/chains (e.g., "Mimino" — Georgian-themed chain popular across Russia) → search for geographic distribution
6. **Coastal features:** Caspian Sea coastline + North Caucasus architecture → Dagestan/Makhachkala

**Key technique — restaurant/brand geolocation:**
- Identify any readable business name or brand logo
- Search for that business + "locations" or "branches"
- Cross-reference with other visual clues (coastline, terrain) to pinpoint exact branch
- Google Maps business search is highly effective for named establishments

**Post-Soviet visual markers:**
- Panel apartment blocks (khrushchyovka/brezhnevka)
- Wide boulevards with central medians
- Concrete bus stops
- Distinctive utility pole designs
- Soviet-era monuments and mosaics

---

## IP Geolocation and Attribution

**Free geolocation services:**
```bash
# IP-API (no key required)
curl "http://ip-api.com/json/103.150.68.150"

# ipinfo.io
curl "https://ipinfo.io/103.150.68.150/json"
```

**Bangladesh IP ranges (common in KCTF):**
- `103.150.x.x` - Bangladesh ISPs
- Mobile prefixes: +880 13/14/15/16/17/18/19

**Correlating location with evidence:**
- Windows telemetry (imprbeacons.dat) contains `CIP` field
- Login history APIs may show IP + OS correlation
- VPN/proxy detection via ASN lookup

---

## Google Lens Cropped Region Search (UTCTF 2026)

**Pattern (W3W1/W3W2):** Challenge image contains multiple elements but only one is useful for identification. Crop to just the relevant portion before searching.

**Technique:**
1. Identify the most distinctive element in the image (shop sign, building facade, landmark)
2. Crop the image to isolate that element — remove surrounding context that adds noise
3. Search the cropped region using Google Lens (`lens.google.com` or right-click → "Search image with Google Lens" in Chrome)
4. Review visually similar results to identify the specific location or business

**When to crop:**
- Shop fronts: crop to just the storefront and signage
- Landmarks: crop to the distinctive architectural feature
- Signs: crop to just the sign text
- Churches/buildings: crop to the unique facade

**Key insight:** Google Lens performs significantly better on cropped regions than full scene images. A full scene may return generic landscape results, while a cropped shop sign returns the exact business with its address.

**Example workflow (W3W2):**
1. Challenge image shows a street scene with a shop
2. Crop to just the shop portion
3. Google Lens identifies the shop and its location
4. Verify on Google Maps Street View
5. Convert coordinates to What3Words

---

## Reflected and Mirrored Text Reading (UTCTF 2026)

**Pattern (W3W3):** Text visible in the image is reflected/mirrored (e.g., sign reflected in water or glass). Must read the text in reverse to identify the location.

**Technique:**
1. Identify reflected text in the image (common in water reflections, glass surfaces, mirrors)
2. Flip the image horizontally to read the text normally
3. If text is partially obscured, search for the readable portion as a prefix/suffix:
   - "Aguas de Lind..." → search `"Aguas de Lind"` → find "Aguas de Lindoia"
4. Use the identified text to locate the place on Google Maps

**Partial text search strategies:**
```text
# Search with wildcards/partial terms
"Aguas de Lind"           # Quoted partial match
"Aguas de Lind" city      # Add context keyword
"Aguas de Lind*" brazil   # Add country if identifiable from image
```

**Image flipping for reflected text:**
```bash
# Flip image horizontally with ImageMagick
convert input.jpg -flop flipped.jpg

# Or with Python/PIL
python3 -c "
from PIL import Image
img = Image.open('input.jpg')
img.transpose(Image.FLIP_LEFT_RIGHT).save('flipped.jpg')
"
```

**Key insight:** When a letter in reflected text is ambiguous (e.g., "T" vs "I"), try both variants as separate searches. Partial text searches with quoted strings are effective for identifying place names even with only 60-70% of the text readable.

---

## What3Words (W3W) Geolocation (UTCTF 2026)

**Pattern (W3W1/W3W2/W3W3):** Photo of a location. Find the exact What3Words address (3-meter precision grid). Flag format: `utflag{word1.word2.word3}`.

**What3Words basics:**
- Divides entire world into 3m x 3m squares, each with a unique 3-word address
- Words are in a SPECIFIC language (English by default)
- Adjacent squares have COMPLETELY different addresses (no spatial correlation)
- Website: https://what3words.com/

**Workflow:**
1. **Identify the location** using standard geolocation techniques (reverse image search, landmarks, signs, architecture)
2. **Get precise GPS coordinates** from Google Maps satellite view
3. **Convert coordinates to W3W** using the website (enter coordinates in search bar)
4. **Fine-tune:** The exact 3m square matters — shift coordinates by small amounts to check adjacent squares

**Coordinate-to-W3W conversion:**
```text
# Navigate to what3words.com and enter coordinates:
# Format: latitude, longitude (e.g., 30.2870, -97.7415)
# Or click on the map at the exact location

# The W3W API requires an API key (not always available in CTF):
# GET https://api.what3words.com/v3/convert-to-3wa?coordinates=30.2870,-97.7415&key=API_KEY
```

**Common pitfalls:**
- **3m precision matters:** A building entrance vs. its parking lot may have different W3W addresses. Match the EXACT viewpoint of the photo.
- **Camera position vs. subject:** The W3W address may refer to where the camera IS, not what it's pointed at.
- **Satellite vs. street-level:** Google Maps pin may not perfectly align with the actual W3W grid.
- **Multiple buildings nearby:** Churches, shops, and landmarks may have several candidate squares.

**Tips for accurate pinpointing:**
- Use Google Street View to match the exact camera angle
- Cross-reference with OpenStreetMap (OSM) for precise building footprints
- Try 5-10 adjacent W3W addresses around your best guess
- The challenge image often shows a specific feature (entrance, sign, landmark) — find THAT exact spot
- **Micro-landmark matching:** Identify small distinctive features in the challenge image (utility poles, pathway rocks, bollards, planters) and locate the same features in Street View to pinpoint the exact 3m square
- **Background building triangulation:** Match buildings visible in the background from the challenge image angle. Find those same buildings in Street View, then determine where the camera must be positioned to produce the same perspective
- **Geographic feature narrowing:** When you know the city but not the exact spot, use distinctive geographic features (lakes, rivers, coastline) visible in the image to narrow the search area before switching to Street View

---

## Monumental Letters / Letreiro Identification (UTCTF 2026)

**Pattern (W3W3):** Photo of large 3D letters spelling a city/location name, often reflected in a pool of water. Common in Latin American cities as tourist landmarks.

**Identification clues:**
- Large colorful 3D block letters
- Often located in main plaza (praça) or tourist area
- May include city name in local language
- Reflection in decorative water pool is a common design

**Search strategy:**
- Google: `"letras monumentales" [city name]` or `"letreiro turístico" [city]`
- OpenStreetMap: search for nodes tagged as `tourism=attraction` near the city center
- Google Maps: search `[city name] sign` or `[city name] letters` and check photos

**Key insight:** These monumental letter installations ("letras monumentales" in Spanish, "letreiro turístico" in Portuguese) are extremely common in Latin American cities. The exact GPS coordinates of the installation can be found on OpenStreetMap or Google Maps photo pins.

---

## Google Maps Crowd-Sourced Photo Verification (MidnightCTF 2026)

**Pattern (Where was Chine):** Verify a candidate location by matching a challenge image against user-submitted Google Maps photos for that place.

**Workflow:**
1. Identify a candidate location name from other OSINT clues (Strava GPS routes, address research, social media posts)
2. Search the location name on Google Maps
3. Click the location pin and browse the **Photos** tab (user-submitted images)
4. Compare scene elements (buildings, trees, paths, water features, signage) against the challenge image
5. Match confirms the location — the place name is typically the flag

**When to use:** After narrowing to a candidate location through non-visual OSINT (fitness routes, addresses, social connections), use Google Maps photos as final visual confirmation. Especially useful for parks, plazas, and landmarks where many tourists upload photos.

**Key insight:** Google Maps aggregates crowd-sourced photos tagged to specific locations. Even when reverse image search fails (because the challenge image is original, not scraped), the same physical scene appears in tourist photos. Search by place name, not by image.

---

## Overpass Turbo Spatial Queries (LAB'OSINT 2025)

**Pattern (Portrait robot):** Find a specific business (newsagent) near a metro entrance in a known city. Overpass Turbo queries OpenStreetMap data to locate POIs by type within a radius of other POIs.

**Tool:** https://overpass-turbo.eu/

**Example — find newsagents within 10m of metro entrances in Barcelona:**
```text
[out:json][timeout:25];
{{geocodeArea:Barcelona}}->.searchArea;

(
  node["railway"="subway_entrance"](area.searchArea);
)->.metros;

(
  node(around.metros:10)["shop"~"newsagent|kiosk"];
  way(around.metros:10)["shop"~"newsagent|kiosk"];
);

out body;
>;
out skel qt;
```

**Common query patterns for OSINT:**
```text
# All cafes near train stations in a city
{{geocodeArea:CityName}}->.a;
node["railway"="station"](area.a)->.stations;
node(around.stations:50)["amenity"="cafe"];

# All ATMs in a neighborhood
node["amenity"="atm"]({{bbox}});

# Hotels near a specific coordinate (lat,lon)
node(around:200,48.8566,2.3522)["tourism"="hotel"];
```

**Key OSM tags for OSINT challenges:**

| Tag | Values |
|-----|--------|
| `shop` | `newsagent`, `kiosk`, `bakery`, `supermarket` |
| `amenity` | `cafe`, `restaurant`, `bank`, `atm`, `pharmacy` |
| `tourism` | `hotel`, `attraction`, `museum`, `viewpoint` |
| `railway` | `station`, `subway_entrance`, `halt` |

**Key insight:** When a challenge image shows a business near a transit stop in a known city, Overpass Turbo can narrow candidates to a handful of locations by querying for the business type within a small radius of transit nodes. Verify each result with Google Street View. The `around` operator (proximity filter) is the most useful feature — it replaces hours of manual map browsing.



---

<!-- Source: quickref.md -->

# ctf-osint — Quick Reference

Inline code / one-liners / common payloads. Loaded on demand from `SKILL.md`. Detailed techniques live in the category-specific support files listed in `SKILL.md`.


## String Identification

- 40 hex chars -> SHA-1 (Tor fingerprint)
- 64 hex chars -> SHA-256
- 32 hex chars -> MD5

## Twitter/X Account Tracking

- Persistent numeric User ID: `https://x.com/i/user/<id>` works even after renames.
- Snowflake timestamps: `(id >> 22) + 1288834974657` = Unix ms.
- Wayback CDX, Nitter, memory.lol for historical data. See [social-media.md](social-media.md).

## Tumblr Investigation

- Blog check: `curl -sI` for `x-tumblr-user` header. Avatar at `/avatar/512`. See [social-media.md](social-media.md).

## Username OSINT

- [whatsmyname.app](https://whatsmyname.app) (741+ sites), [namechk.com](https://namechk.com). Watch for platform false positives. See [social-media.md](social-media.md).

## Image Analysis & Reverse Image Search

- Google Lens (crop to region of interest), Google Images, TinEye, Yandex (faces). Check corners for visual stego. Twitter strips EXIF. See [geolocation-and-media.md](geolocation-and-media.md).
- **Cropped region search:** Isolate distinctive elements (shop signs, building facades) and search via Google Lens for better results than full-scene search. See [geolocation-and-media.md](geolocation-and-media.md).
- **Reflected text:** Flip mirrored/reflected text (water, glass) horizontally; search partial text with quoted strings. See [geolocation-and-media.md](geolocation-and-media.md).

## Geolocation

- Railroad signs, infrastructure maps (OpenRailwayMap, OpenInfraMap), process of elimination. See [geolocation-and-media.md](geolocation-and-media.md).
- **Street View panorama matching:** Feature extraction + multi-metric image similarity ranking against candidate panoramas. Useful when challenge image is a crop of a Street View photo. See [geolocation-and-media.md](geolocation-and-media.md).
- **Road sign OCR:** Extract text from directional signs (town names, route numbers) to pinpoint road corridors. Driving side + sign style + script identify the country. See [geolocation-and-media.md](geolocation-and-media.md).
- **Architecture + brand identification:** Post-Soviet concrete = Russia/CIS; named businesses → search locations/branches → cross-reference with coastline/terrain. See [geolocation-and-media.md](geolocation-and-media.md).

## MGRS Coordinates

- Grid format "4V FH 246 677" -> online converter -> lat/long -> Google Maps. See [geolocation-and-media.md](geolocation-and-media.md).

## Google Plus Codes

- Format `XXXX+XXX` (chars: `23456789CFGHJMPQRVWX`). Drop a pin on Google Maps → Plus Code appears in details. Free, no API key needed. See [geolocation-and-media.md](geolocation-and-media.md).

## Metadata Extraction

```bash
exiftool image.jpg           # EXIF data
pdfinfo document.pdf         # PDF metadata
mediainfo video.mp4          # Video metadata
```

## Google Dorking

```text
site:example.com filetype:pdf
intitle:"index of" password
```

**Image TBS filters:** Append `&tbs=itp:face` to Google Image URLs to filter for faces only (strips logos/banners). See [web-and-dns.md](web-and-dns.md).

## Google Docs/Sheets

- Try `/export?format=csv`, `/pub`, `/gviz/tq?tqx=out:csv`, `/htmlview`. See [web-and-dns.md](web-and-dns.md).

## DNS Reconnaissance

```bash
dig -t txt subdomain.ctf.domain.com
dig axfr @ns.domain.com domain.com  # Zone transfer
```

Always check TXT, CNAME, MX for CTF domains. See [web-and-dns.md](web-and-dns.md).

## Tor Relay Lookups

- `https://metrics.torproject.org/rs.html#simple/<FINGERPRINT>` -- check family, sort by "first seen". See [web-and-dns.md](web-and-dns.md).

## GitHub Repository Analysis

- Check issue comments, PR reviews, commit messages, wiki edits via `gh api`. See [web-and-dns.md](web-and-dns.md).

## Telegram Bot Investigation

- Find bot references in browser history, interact via `/start`, answer verification questions. See [web-and-dns.md](web-and-dns.md).

## FEC Political Donation Research

- FEC.gov for committee receipts; 501(c)(4) orgs obscure original funders. See [web-and-dns.md](web-and-dns.md).

## IP Geolocation

```bash
curl "http://ip-api.com/json/103.150.68.150"
```

See [geolocation-and-media.md](geolocation-and-media.md).

## Unicode Homoglyph Steganography

**Pattern:** Visually-identical Unicode characters from different blocks (Cyrillic, Greek, Math) encode binary data in social media posts. ASCII = 0, homoglyph = 1. Group bits into bytes for flag. See [social-media.md](social-media.md#unicode-homoglyph-steganography-on-bluesky-metactf-2026).

## BlueSky Public API

No auth needed. Endpoints: `public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=...`, `app.bsky.actor.searchActors`, `app.bsky.feed.getAuthorFeed`. Check all replies to official posts. See [social-media.md](social-media.md#unicode-homoglyph-steganography-on-bluesky-metactf-2026).

## Resources

- **Shodan** - Internet-connected devices
- **Censys** - Certificate and host search
- **VirusTotal** - File/URL reputation
- **WHOIS** - Domain registration
- **Wayback Machine** - Historical snapshots



---

<!-- Source: social-media.md -->

# Social Media OSINT

## Table of Contents
- [Twitter/X Account Tracking](#twitterx-account-tracking)
- [Tumblr Investigation](#tumblr-investigation)
- [BlueSky Advanced Search](#bluesky-advanced-search)
- [Username OSINT](#username-osint)
- [Platform False Positives](#platform-false-positives)
- [Social Media General Tips](#social-media-general-tips)
- [Multi-Platform OSINT Chain](#multi-platform-osint-chain)
- [MetaCTF OSINT Challenge Patterns](#metactf-osint-challenge-patterns)
- [Unicode Homoglyph Steganography on BlueSky (MetaCTF 2026)](#unicode-homoglyph-steganography-on-bluesky-metactf-2026)
- [Strava Fitness Route OSINT (MidnightCTF 2026)](#strava-fitness-route-osint-midnightctf-2026)
- [Discord API Enumeration](#discord-api-enumeration)

---

## Twitter/X Account Tracking

**Persistent numeric User ID (key technique):**
- Every Twitter/X account has a permanent numeric ID that never changes
- Access any account by ID: `https://x.com/i/user/<numeric_id>` -- works even after username changes
- Find user ID from archived pages (JSON-LD `"author":{"identifier":"..."}`)
- Useful when username is deleted/changed but you have the ID from forensic artifacts

**Username rename detection:**
- Twitter User IDs persist across username changes; t.co shortlinks point to OLD usernames
- Wayback CDX API to find archived profiles: `http://web.archive.org/cdx/search/cdx?url=twitter.com/USERNAME*&output=json`
- Archived pages contain JSON-LD with user ID, creation date, follower/following counts
- t.co links in archived tweets reveal previous usernames (the redirect URL contains the username at time of posting)
- Same tweet ID accessible under different usernames = confirmed rename

**Alternative Twitter data sources:**
- Nitter instances (e.g., `nitter.poast.org/USERNAME`) show tweets without login
- Syndication API: `https://syndication.twitter.com/srv/timeline-profile/screen-name/USERNAME`
- Twitter Snowflake IDs encode timestamps: `(id >> 22) + 1288834974657` = Unix ms
- memory.lol and twitter.lolarchiver.com track username history

**Wayback Machine for Twitter:**
```bash
# Find all archived URLs for a username
curl "http://web.archive.org/cdx/search/cdx?url=twitter.com/USERNAME*&output=json&fl=timestamp,original,statuscode"

# Also check profile images
curl "http://web.archive.org/cdx/search/cdx?url=pbs.twimg.com/profile_images/*&output=json"

# Check t.co shortlinks
curl "http://web.archive.org/cdx/search/cdx?url=t.co/SHORTCODE&output=json"
```

## Tumblr Investigation

**Blog existence check:**
- `curl -sI "https://USERNAME.tumblr.com"` -> look for `x-tumblr-user` header (confirms blog exists even if API returns 401)
- Tumblr API may return 401 (Unauthorized) but the blog is still publicly viewable via browser

**Extracting post content from Tumblr HTML:**
- Tumblr embeds post data as JSON in the page HTML
- Search for `"content":[` to find post body data
- Posts contain `type: "text"` with `text` field, and `type: "image"` with media URLs
- Avatar URL pattern: `https://64.media.tumblr.com/HASH/HASH-XX/s512x512u_c1/FILENAME.jpg`

**Avatar as flag container:**
- Direct avatar endpoint: `https://api.tumblr.com/v2/blog/USERNAME.tumblr.com/avatar/512`
- Or simply: `https://USERNAME.tumblr.com/avatar/512` (redirects to CDN URL)
- Available sizes: 16, 24, 30, 40, 48, 64, 96, 128, 512
- Flags may be hidden as small text in avatar images (visual stego, not binary stego)
- Always download highest resolution (512) and zoom in on all areas

## BlueSky Advanced Search

**Pattern (Ms Blue Sky):** Find target's posts on BlueSky social media.

**Search filters:**
```text
from:username        # Posts from specific user
since:2025-01-01     # Date range
has:images           # Posts with images
```

**Reference:** https://bsky.social/about/blog/05-31-2024-search

## Username OSINT

- [namechk.com](https://namechk.com) - Check username across platforms
- [whatsmyname.app](https://whatsmyname.app) - Username enumeration (741+ sites)
- [Osint Industries](https://osint.industries) - Cross-platform people search (paid, covers fitness/niche platforms)
- Search `"username"` in quotes on major platforms

**Username metadata mining:**
Usernames often embed geographic or temporal signals in their structure. Extract and research numeric suffixes, prefixes, or embedded patterns:

| Pattern | Example | Signal |
|---------|---------|--------|
| Trailing digits = postal/ZIP code | `LinXiayu35170` | 35170 = Bruz, France |
| Birth year suffix | `jsmith1998` | Born 1998 |
| Area code | `user212nyc` | 212 = Manhattan |
| Country code | `player44uk` | +44 = United Kingdom |

Cross-reference extracted codes with postal code databases, phone number registries, or geographic gazetteers to narrow the subject's location. (MidnightCTF 2026)

**Username chain tracing (account renames):**
1. Start with known username -> find Wayback archives
2. Look for t.co links or cross-references to other usernames in archived pages
3. Discovered new username -> enumerate across ALL platforms again
4. Repeat until you find the platform with the flag

**Priority platforms for CTF username enumeration:**
- Twitter/X, Tumblr, GitHub, Reddit, Bluesky, Mastodon
- Spotify, SoundCloud, Steam, Keybase
- Strava, Garmin Connect, MapMyRun (fitness/GPS — leak physical locations)
- Pastebin, LinkedIn, YouTube, TikTok
- bio-link services (linktr.ee, bio.link, about.me)

## Platform False Positives

Platforms that return 200 but no real profile:
- Telegram (`t.me/USER`): Always returns 200 with "Contact @USER" page; check for "View" vs "Contact" in title
- TikTok: Returns 200 with "Couldn't find this account" in body
- Smule: Returns 200 with "Not Found" in page content
- linkin.bio: Redirects to Later.com product page for unclaimed names
- Instagram: Returns 200 but shows login wall (may or may not exist)

## Social Media General Tips

- Check Wayback Machine for deleted posts on Bluesky, Twitter, etc.
- Unlisted YouTube videos may be linked in deleted posts
- Bio links lead to itch.io, personal sites with more info
- Search `"username"` with quotes on platform-specific searches
- Challenge titles are often hints (e.g., "Linked Traces" -> LinkedIn / linked accounts)
- **Twitter strips EXIF** on upload - don't waste time on stego for Twitter-served images
- **Tumblr preserves more metadata** in avatars than in post images

## Multi-Platform OSINT Chain

**Pattern (Massive-Equipment393):** Reddit username -> Spotify social link -> Base58-encoded string -> Spotify playlist descriptions (base64) -> first-letter acrostic from song titles.

**Key techniques:**
- Base58 decoding for non-standard encodings
- Spotify playlists encode data in descriptions and song title initials
- Platform chaining: each platform links to the next

## MetaCTF OSINT Challenge Patterns

**Common flow:**
1. Start image with hidden EXIF/metadata -> extract username
2. Username enumeration (Sherlock/WhatsMyName) across platforms
3. Find profile on platform X with clues pointing to platform Y
4. Flag hidden on the final platform (Spotify bio, BlueSky post, Tumblr avatar, etc.)

**Platform-specific flag locations:**
- Spotify: playlist names, artist bio
- BlueSky: post content
- Tumblr: avatar image, post text
- Reddit: post/comment content
- Smule: song recordings or bio
- SoundCloud: track description

**Key techniques:**
- Account rename tracking via Wayback + t.co links
- Cross-platform username correlation
- Visual inspection of all profile images at max resolution
- Song lyric identification -> artist/song as flag component

## Unicode Homoglyph Steganography on BlueSky (MetaCTF 2026)

**Pattern (Skybound Secrets):** Flag hidden in a Bluesky post using Unicode homoglyph steganography — visually identical characters from different Unicode blocks encode binary data.

**Detection:**
- Post text looks normal but character-by-character analysis reveals non-ASCII codepoints
- Characters from Cyrillic (`а` U+0430 vs `a` U+0061), Greek, Armenian, Mathematical Monospace, etc.
- Each character encodes 1 bit: ASCII = 0, homoglyph = 1

**Bluesky API search workflow:**
```bash
# Search for posts about the CTF
curl -s "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=metactf+flash+ctf&sort=latest" | jq '.posts[].record.text'

# Search for specific accounts
curl -s "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors?q=metactf" | jq '.actors[].handle'

# Get profile
curl -s "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=metactf.bsky.social" | jq

# Get author feed (all posts)
curl -s "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=metactf.bsky.social&limit=50" | jq '.feed[].post.record.text'

# Get post thread (including replies)
curl -s "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?uri=at://did:plc:.../app.bsky.feed.post/..." | jq
```

**Decoding homoglyph steganography:**
```python
def decode_homoglyph_stego(text):
    bits = []
    for ch in text:
        if ch in ('\u2019',):  # Platform auto-inserted right single quote
            continue  # Skip, not intentional homoglyph
        if ord(ch) < 128:
            bits.append(0)  # Standard ASCII
        else:
            bits.append(1)  # Unicode homoglyph = 1 bit

    # Group into bytes (MSB first)
    flag = ''
    for i in range(0, len(bits) - 7, 8):
        byte_val = 0
        for j in range(8):
            byte_val = (byte_val << 1) | bits[i + j]
        flag += chr(byte_val)
    return flag
```

**Common homoglyph pairs:**
| ASCII | Homoglyph | Unicode Block |
|-------|-----------|---------------|
| `a` (U+0061) | `а` (U+0430) | Cyrillic |
| `o` (U+006F) | `о` (U+043E) | Cyrillic |
| `e` (U+0065) | `е` (U+0435) | Cyrillic |
| `s` (U+0073) | `ѕ` (U+0455) | Cyrillic DZE |
| `t` (U+0074) | `𝚝` (U+1D69D) | Math Monospace |
| `p` (U+0070) | `р` (U+0440) | Cyrillic |

**Key lessons:**
- Check ALL replies to official CTF posts, not just the main post
- Platform auto-formatting (smart quotes `'` → `'`) must be excluded from bit encoding
- Hints like "hype comes with its own secrets" suggest steganography in the social media posts themselves
- Bluesky public API requires no authentication — use `public.api.bsky.app`

---

## Strava Fitness Route OSINT (MidnightCTF 2026)

**Pattern (Where was Chine):** Target's physical location identified through fitness tracking data. Username discovered on Twitter → alias found in GitHub code → alias searched on Strava → running route endpoint reveals location.

**Strava public data exposure:**
- Public athlete profiles: `https://www.strava.com/athletes/<id>`
- Activity maps show GPS routes with start/end points
- Even "privacy zones" can be circumvented by analyzing route shapes outside the zone
- Segment leaderboards reveal athlete locations without following them

**Location extraction workflow:**
1. Find target's Strava profile via username enumeration (Whatsmyname, Osint Industries)
2. Check public activities for GPS route maps
3. Identify route start/end points or frequent locations
4. Search the endpoint location on Google Maps
5. Verify with Google Maps user-submitted photos (see [geolocation-and-media.md](geolocation-and-media.md#google-maps-crowd-sourced-photo-verification-midnightctf-2026))

**Key insight:** Fitness apps are high-value OSINT targets because users rarely restrict activity visibility. A single public run reveals home/work neighborhoods. Cross-reference GPS endpoints with Google Maps to identify specific parks, buildings, or landmarks.

**Detection:** Challenge mentions exercise, running, cycling, fitness, GPS, or health tracking. Target persona has an active/athletic profile.

---

## Discord API Enumeration

**Pattern (Insanity 1 & 2, 0xFun 2026):** Flags hidden in Discord server metadata not visible in normal UI.

**Hiding spots:**
- Role names
- Animated GIF emoji (flag in 2nd frame with tiny duration)
- Message embeds
- Server description, stickers, events

```bash
# Enumerate with user token
TOKEN="your_token"
# List roles
curl -H "Authorization: $TOKEN" "https://discord.com/api/v10/guilds/GUILD_ID/roles"
# List emojis
curl -H "Authorization: $TOKEN" "https://discord.com/api/v10/guilds/GUILD_ID/emojis"
# Search messages
curl -H "Authorization: $TOKEN" "https://discord.com/api/v10/guilds/GUILD_ID/messages/search?content=flag"
```

**Animated emoji:** Download GIF, extract frames -- hidden data in brief frames invisible at normal speed.



---

<!-- Source: web-and-dns.md -->

# Web and DNS OSINT

## Table of Contents
- [Google Dorking](#google-dorking)
- [Google Docs/Sheets in OSINT](#google-docssheets-in-osint)
- [DNS Reconnaissance](#dns-reconnaissance)
- [DNS TXT Record OSINT](#dns-txt-record-osint)
- [Tor Relay Lookups](#tor-relay-lookups)
- [GitHub Repository Comments](#github-repository-comments)
- [Telegram Bot Investigation](#telegram-bot-investigation)
- [FEC Political Donation Research](#fec-political-donation-research)
- [Wayback Machine](#wayback-machine)
- [WHOIS Investigation](#whois-investigation)
- [Resources](#resources)

---

## Google Dorking

```text
site:example.com filetype:pdf
intitle:"index of" password
inurl:admin
"confidential" filetype:doc
```

**Google Image TBS (To Be Searched) parameters:**

Append `&tbs=` filters to Google Image search URLs for precision filtering:

| Filter | Parameter | Example |
|--------|-----------|---------|
| Faces only | `itp:face` | Find profile photos |
| Clipart | `itp:clipart` | Logos, icons |
| Animated GIF | `itp:animated` | Animated images |
| Specific color | `ic:specific,isc:green` | Dominant color filter |
| Transparent BG | `ic:trans` | PNGs with transparency |
| Large images | `isz:l` | High resolution only |
| Min resolution | `isz:lt,islt:2mp` | Greater than 2 megapixels |

**Combined example:** Search LinkedIn for face photos of interns at a company:
```text
https://www.google.com/search?q="orange"+"alternant"+site:linkedin.com&tbm=isch&tbs=itp:face
```

**Key insight:** The `itp:face` filter is especially useful for OSINT — it strips out logos, banners, and UI screenshots from results, leaving only profile photos. Combine with `site:` and date range (`after:YYYY-MM-DD`) for targeted reconnaissance.

## Google Docs/Sheets in OSINT

- Suspects may link to Google Sheets/Docs in tweets or posts
- Try public access URLs:
  - `/export?format=csv` - Export as CSV
  - `/pub` - Published version
  - `/gviz/tq?tqx=out:csv` - Visualization API CSV export
  - `/htmlview` - HTML view
- Private sheets require authentication; flag may be in the sheet itself
- Sheet IDs are stable identifiers even if sharing settings change

## DNS Reconnaissance

Flags often in TXT records of subdomains, not root domain:
```bash
dig -t txt subdomain.ctf.domain.com
dig -t any domain.com
dig axfr @ns.domain.com domain.com  # Zone transfer
```

## DNS TXT Record OSINT

```bash
dig TXT ctf.domain.org
dig TXT _dmarc.domain.org
dig ANY domain.org
```

**Lesson:** DNS TXT records are publicly queryable. Always check TXT, CNAME, MX for CTF domains and subdomains.

## Tor Relay Lookups

```text
https://metrics.torproject.org/rs.html#simple/<FINGERPRINT>
```
Check family members and sort by "first seen" date for ordered flags.

## GitHub Repository Comments

**Pattern (Rogue, VuwCTF 2025):** Hidden information in GitHub repo comments (issue comments, PR reviews, commit messages, wiki edits).

**Check:** `gh api repos/OWNER/REPO/issues/comments`, `gh api repos/OWNER/REPO/commits`, wiki edit history.

## Telegram Bot Investigation

**Pattern:** Forensic artifacts (browser history, chat logs) may reference Telegram bots that require active interaction.

**Finding bot references in forensics:**
```python
# Search browser history for Telegram URLs
import sqlite3
conn = sqlite3.connect("History")  # Edge/Chrome history DB
cur = conn.cursor()
cur.execute("SELECT url FROM urls WHERE url LIKE '%t.me/%'")
# Example: https://t.me/comrade404_bot
```

**Bot interaction workflow:**
1. Visit `https://t.me/<botname>` -> Opens in Telegram
2. Start conversation with `/start` or bot's custom command
3. Bot may require verification (CTF-style challenges)
4. Answers often require knowledge from forensic analysis

**Verification question patterns:**
- "Which user account did you use for X?" -> Check browser history, login records
- "Which account was modified?" -> Check Security.evtx Event 4781 (rename)
- "What file did you access?" -> Check MRU, Recent files, Shellbags

**Example bot flow:**
```text
Bot: "TIER 1: Which account used for online search?"
-> Answer from Edge history showing Bing/Google searches

Bot: "TIER 2: Which account name did you change?"
-> Answer from Security event log (account rename events)

Bot: [Grants access] "Website: http://x.x.x.x:5000, Username: mehacker, Password: flaghere"
```

**Key insight:** Bot responses may reveal:
- Attacker's real identity/handle
- Credentials to secondary systems
- Direct flag components
- Links to hidden web services

## FEC Political Donation Research

**Pattern (Shell Game):** Track organizational donors through FEC filings.

**Key resources:**
- [FEC.gov](https://www.fec.gov/data/) - Committee receipts and expenditures
- 501(c)(4) organizations can donate to Super PACs without disclosing original funders
- Look for largest organizational donors, then research org leadership (CEO/President)

## Wayback Machine

```bash
# Find all archived URLs for a site
curl "http://web.archive.org/cdx/search/cdx?url=example.com*&output=json&fl=timestamp,original,statuscode"
```

- Check for deleted posts, old profiles, cached pages
- CDX API for programmatic access to archive index

## WHOIS Investigation

```bash
# Basic WHOIS lookup
whois example.com

# Key fields to extract:
# - Registrant name/email/org (often redacted by privacy services)
# - Creation/expiration dates (timeline correlation)
# - Name servers (shared hosting identification)
# - Registrar (can indicate sophistication level)

# Historical WHOIS (before privacy was enabled)
# Use SecurityTrails, WhoisXML API, or DomainTools
curl "https://api.securitytrails.com/v1/domain/example.com/whois" \
  -H "APIKEY: YOUR_KEY"

# Reverse WHOIS — find all domains registered by same entity
# Search by registrant email, org name, or phone number
curl "https://reverse-whois-api.whoisxmlapi.com/api/v2" \
  -d '{"searchType":"current","mode":"purchase","basicSearchTerms":{"include":["target@email.com"]}}'

# IP WHOIS (find network owner)
whois 1.2.3.4
# Look for: NetName, OrgName, CIDR range, abuse contact

# ASN lookup
whois -h whois.radb.net AS12345
# Or use bgp.tools: https://bgp.tools/as/12345
```

**Key insight:** WHOIS data is most useful for timeline correlation (when was the domain registered relative to CTF events?), reverse lookups (what other domains share the same registrant?), and identifying shared infrastructure. Historical WHOIS via SecurityTrails or Wayback Machine can reveal pre-privacy registrant details.

---

## Resources

- **Shodan** - Internet-connected devices
- **Censys** - Certificate and host search
- **VirusTotal** - File/URL reputation
- **WHOIS** - Domain registration
- **Wayback Machine** - Historical snapshots
