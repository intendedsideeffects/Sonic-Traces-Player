# Sonic Traces Player

### A cartography of sound

**Sonic Traces** is an interactive Tableau visualization exploring six months of listening history across a 24-hour clock.

This repository contains the custom audio extension built for the visualization. It connects tracks in the Tableau view with audio previews, allowing users to explore the data not only visually, but through sound.

**[Explore Sonic Traces on Tableau Public →](https://public.tableau.com/app/profile/janina.grauel/viz/SonicTraces-SoundOn/SonicTraces)**

![Sonic Traces interactive Tableau visualization](sonic_traces.png)

**Built with:** JavaScript · HTML · CSS · Tableau Extensions API

## Deployment

1. Copy your existing `tableau.extensions.1.latest.js` into this folder beside `index.html`.
2. Upload all files and the `api` folder to a new GitHub repository.
3. In Vercel choose Add New → Project, import the repository, framework Other, then deploy.
4. Test: `https://YOUR-PROJECT.vercel.app/api/deezer-preview?id=143661438`.
5. Replace `YOUR-VERCEL-PROJECT` in the `.trex` template with the real project name.
6. Load the new `.trex` in Tableau Desktop and publish again.

`Radial` needs `deezer_track_id`, `Title`, and `Artist` on Detail.
