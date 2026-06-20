# Style sample previews

Committed reference images for the Studio **Style** picker. Safe to keep in git — **not** touched by video cleanup (only `01-script/` … `06-output/` reset).

| File | Purpose |
|------|---------|
| `variants.json` | Style names + `image_style` prompts (source of truth) |
| `explore_XX.png` | Preview thumbnail for style XX |
| `manifest.json` | Catalog mirror (optional; used by explore runs) |

To add a new style: add a row to `variants.json`, generate a sample PNG as `explore_XX.png`, commit both.

Ephemeral test runs write to `tracker/style-explore-run/` (gitignored).
