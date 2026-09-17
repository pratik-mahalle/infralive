# Cloudwake identity

A cloud silhouette and a pulse share one continuous outline. Midnight navy keeps the app icon
quiet; mint gives the mark contrast. The menu bar uses the same geometry as a macOS template
image, so the operating system supplies the appropriate color.

| Asset | Use |
| --- | --- |
| [App logo](assets/cloudwake.svg) | Scalable square logo with a transparent outer margin |
| [Standalone mark](assets/cloudwake-mark.svg) | Single-color symbol on light backgrounds |
| [PNG icon](../macos/Assets/Cloudwake.png) | 1024px app and documentation artwork |
| [Swift vector master](../macos/Sources/CostBar/BrandMark.swift) | Shared geometry for the native app and icon renderer |

Palette: midnight `#0F1D28`, mint `#71EFC5`, edge `#283D48`. Keep clear space around the mark,
use it without text at small sizes, and use the system font for the product name in the app.

Run `bash macos/build.sh` to regenerate every macOS icon size and the PNG from the Swift master.
The SVG exports use the same 100-unit path. Update them when changing the vector geometry.

The product was previously called CloudPulse. The bundle identifier, preference keys, Python
package/CLI (`aws-cost-agent`), and `cloudpulse-*` AWS resource names and ownership tags remain
stable so existing connections, notification permissions, and deployed monitoring keep working.
