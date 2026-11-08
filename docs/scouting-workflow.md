# Fictional scouting walkthrough

From the repository root, use the existing environment:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

Open <http://127.0.0.1:8501>. Stop the app with Ctrl+C. On Linux, use
`.venv/bin/python` in place of the Windows interpreter path. The app builds all
invented match counts and profiles in memory through the existing importer and
profile code; it needs no provider credentials, private cache or generated files.

1. Keep **Lumen Ash · Mossbridge · Regular season** as the reference player. The
   compact summary shows 180 recorded minutes and two accepted appearances. Expand
   **Reference stats and method** for full rates, coverage and the fixed scaling
   reference. **Fictional demo** and the provisional eligibility criteria stay
   visible above search.
2. Search candidates by player or club name. Select **Add Mira Reed**, **Add Neri
   Lark** and **Add Pax Ember** on their result cards. The **Shortlist · 3** link
   beside search jumps to saved entries. Saved samples have disabled Add buttons.
3. **Session shortlist** appears beside results on desktop and below them on narrow
   screens. Under **Shortlist side by side**, **Players to compare** initially
   selects all saved candidates. Cards show the reference alongside their minutes,
   appearances, distances and four v2 per-90 rates. They stack into complete cards
   on mobile. Adjust the comparison selection without deleting saved samples.
   Write up to 240 characters in **Note for Mira Reed** to remember why you saved
   that player. Click away or press Ctrl+Enter to apply an edit. Notes stay with
   each saved sample when you search or change the reference, including an
   ineligible reference.
4. Candidate cards describe their two largest distance features in plain language,
   such as “More recorded duels; higher pass rate.” These compare per-90 rates with
   the reference and use the engine's existing top-two feature selection. Expand
   **Details for Pax Ember** or **Saved details for Pax Ember** for rate differences,
   precise weighted squared contributions and full-precision structured values.
   All four contributions sum to distance squared. Lower distance describes closer
   recorded activity, not ability. Exact ties retain their shared distance group.
5. Change **Reference player** to **Mira Reed**. All three samples stay saved; Mira is
   identified as the current reference and appears once in the comparison cards.
   Pax's distance and contributors recalculate. The five-profile scaling fit stays
   fixed. Removing a saved sample also removes it from the comparison selection.
6. Search for **Rumi** under **Search candidates**. There are zero eligible
   candidates: Rumi's dribble inputs cover only one of two accepted appearances.
   Expand **Why some profiles are excluded** for the missing dribble count and
   coverage. The saved shortlist stays available. Search **Sable** to inspect a
   30-minute/one-appearance sample against the provisional 90-minute/two-appearance
   screen. Search an unknown name to inspect an empty result set. Clear the search
   to restore the full pool.
7. Choose **Rumi Mist** as the reference player. The comparison warning explains
   the missing inputs. Saved rates remain visible, and candidate distances become
   unavailable. Changing back to an eligible reference recalculates the distances.
8. Use **Remove Mira Reed**, **Remove Pax Ember**, or **Clear shortlist**. These
   actions remove the saved samples and their notes. Adding the player again starts
   with an empty note. An empty shortlist explains how to add a result again.

Saved entries belong to the current Streamlit session and use the full provider,
competition, season, stage, club and player identity. Search and reference changes
do not clear them. A new browser session starts empty; there is no account storage,
disk persistence or export. Distances are recomputed from v2 engine results rather
than retained from an earlier reference or filtered search.

This flow uses the existing provisional **90 recorded minutes/two appearances**
comparison screen with complete v2 feature coverage. The offline stability study's
180/3 candidate screen remains separate. All provider semantics, missing values,
scope exclusions, same-player exclusions and exact-distance ties retain the
[comparison contract](similarity.md). The app exposes no real-data mode. The
fictional declaration and disabled real-player ranking/integration flags remain
in force; this workflow establishes no real scouting conclusion.

Run the focused interface tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_ui.py -v
```
