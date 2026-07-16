# Sonic Traces Player

### A cartography of sound

**Sonic Traces** is an interactive Tableau data story built from six months of a friend's listening history. Every song is mapped onto a 24-hour clock, revealing recurring listening patterns and the moments they belong to.

Viewers can select meaningful moments, explore the songs associated with them, and listen to audio previews directly from the visualization.

To make this possible, I built a custom audio extension that connects the Tableau visualization with track previews. A Python script matches tracks from the original listening data with Deezer and prepares the information required by the player.

By combining **data preparation, visualization, interaction and sound**, the project turns personal listening data into an exploratory data experience.

**[Explore Sonic Traces on Tableau Public →](https://public.tableau.com/app/profile/janina.grauel/viz/SonicTraces-SoundOn/SonicTraces)**

![Sonic Traces](sonic_traces.png)

## How it works

The project combines Python, Tableau and a custom JavaScript extension:

1. **Python** processes the listening data and matches tracks with Deezer to retrieve the information required for audio previews.
2. **Tableau** maps the listening history onto a 24-hour radial visualization and provides the interactive exploration.
3. **JavaScript** connects selections in Tableau to the custom audio player.
4. The **Tableau Extensions API** enables communication between the visualization and the player.

This creates a connection between the visual patterns in the listening history and the music behind the data.

## Tools

`Python` · `Tableau` · `JavaScript` · `HTML` · `CSS` · `Tableau Extensions API`

## Repository structure

- `update_sonic_traces_previews.py` — track matching and preparation of Deezer preview data
- `player.js` — audio player logic and Tableau interaction
- `index.html` — extension interface
- `style.css` — player styling
- `api/` — API functionality used by the player
- `SonicTracesPlayer_PUBLIC_TEMPLATE.trex` — Tableau extension configuration template

## Deployment

The extension is deployed separately from the Tableau visualization and loaded into Tableau through the `.trex` configuration.

For deployment, the project can be hosted on Vercel and the corresponding project URL added to the `.trex` file.
