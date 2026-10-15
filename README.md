# Unraid Templates

Docker templates and plugins for Unraid Community Applications.

## Applications

Docker containers, installed from a template.

| Application | Description |
|---|---|
| [Stillwater](https://github.com/sydlexius/stillwater) | Artist metadata and image management for Emby, Jellyfin, and Kodi |
| [Canticle](https://github.com/sydlexius/canticle) | Time-synced (.lrc) lyrics for your music library, on a schedule and via Lidarr webhooks |

## Plugins

Native Unraid plugins, which run on the host rather than in a container.

| Plugin | Description |
|---|---|
| [Watch-Aware Preloader](https://github.com/sydlexius/watch-aware-preloader) | Warms the page cache with what each Emby or Jellyfin user is likely to play next, so playback skips the disk spin-up wait |

## Usage

**From Community Applications (both kinds).** Search the **Apps** tab for the
application or plugin by name and install it from there.

**Docker templates only.** To get these templates without waiting for a
Community Applications listing, add this repository URL under
**Apps > Settings > Repository**:

```
https://github.com/sydlexius/unraid-templates
```

**Plugins only.** To install a plugin directly, paste its `.plg` URL under
**Plugins > Install Plugin**. Each plugin's URL is the `<PluginURL>` in its
wrapper under `plugins/`, and is also given in the plugin's own README.

## Layout

| Path | Contents |
|---|---|
| `templates/<name>.xml` | Docker container templates (`<Container>` root) |
| `plugins/<name>.xml` | Plugin wrappers (`<Plugin>` root) |
| `ca_profile.xml` | Repository description shown by Community Applications |

A plugin wrapper describes a `.plg` published by the plugin's own repository,
and the two must agree. CI fetches each wrapper's `<PluginURL>` daily and on
every pull request, and fails if the published `.plg` disagrees on `pluginURL`
(which must match exactly), `support`, `min`, `max`, or `icon`. It also fails if
`ca_profile.xml` has an empty `<Profile>`. To add a plugin,
add its wrapper under `plugins/` and a row to the table above; the check picks
it up automatically.

## Support

Open an issue on the relevant application's or plugin's GitHub repository.

## License

GPL-3.0
