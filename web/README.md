# Download website

Static HTML/CSS/JavaScript. Downloads link directly to the published GitHub
release; the Linux archive is not copied to Netlify. No build or dependencies.
Light and dark themes follow the device preference until a visitor uses the
header switch; their choice is saved locally in the browser. GitHub links invite
visitors to star, fork and reuse the project.

## Netlify

1. Commit/push this repo, then in Netlify choose **Add new project → Import an
   existing project → GitHub** and select **Desktop-Buddy**.
2. Branch: `main`. Leave the base directory and build command empty. Publish
   directory: `web` (the root `netlify.toml` already sets this).
3. Select **Deploy**. Netlify gives you a URL and HTTPS; add your domain later
   in domain management.

Alternatively, drag the `web/` folder into Netlify's manual deploy area.

Local preview from the repo root: `python3 -m http.server 8080 --directory web`,
then open http://localhost:8080.

For a new release, update the version, archive filename and download links in
`web/index.html`. Keep the system requirements aligned with the Linux build.
Character previews are exported from the app's existing QPainter renderer.
