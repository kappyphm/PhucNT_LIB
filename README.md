# PhucNT KiCad Library

Symbols, footprints and 3D models for PhucNT projects.

Requires KiCad 9.0 or newer.

## Contents

- BMP388 breakout module
- ICM20602 breakout module
- WeAct STM32F405RGT6 64-pin core board

## Installation

### Plugin and Content Manager (recommended)

1. Open KiCad and go to **Preferences > Plugins and Content Manager**.
2. Open **Manage repositories** and add:

   ```text
   https://raw.githubusercontent.com/kappyphm/PhucNT_LIB/main/dist/repository.json
   ```

3. Install **PhucNT KiCad Library** from the repository.
4. Keep the library nickname prefix at the default `PCM_` value. All symbol
   footprint references use `PCM_PhucNT_lib:...`; changing the prefix breaks
   those links.
5. Restart KiCad if the library does not appear immediately.

### Install from file

Download the latest `com.github.kappyphm.phucnt-lib_v*_pcm.zip` from the
[releases page](https://github.com/kappyphm/PhucNT_LIB/releases), then use
**Install from file** in the Plugin and Content Manager. Keep the `PCM_` prefix.

## Library layout

```text
symbols/PhucNT_lib.kicad_sym
footprints/PhucNT_lib.pretty/
3dmodels/PhucNT_Lib.3dshapes/
```

The PCM package installs the 3D models under:

```text
${KICAD9_3RD_PARTY}/3dmodels/com_github_kappyphm_phucnt-lib/PhucNT_Lib.3dshapes/
```

## Development

Build the package and repository indexes:

```powershell
python scripts/build_pcm.py --tag v1.0.0
```

Validate the source tree without writing output:

```powershell
python scripts/build_pcm.py --check-only
```

Run the tests:

```powershell
python -m unittest discover -s tests -v
```

The build script only uses the Python standard library. It validates the
metadata, symbol footprint references, footprint names and 3D model paths,
then creates the PCM archive and updates `dist/packages.json` and
`dist/repository.json`.

## Releases

Releases are built by `.github/workflows/release.yml` when a tag matching
`v*` is pushed. The tag version must match `metadata.json`, for example tag
`v1.0.0` and version `1.0.0`. The workflow verifies the source on `main`,
builds the archive, creates a GitHub release and uploads the archive as a
release asset, then commits the updated indexes back to `main`.

## License

This library is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

Third-party 3D models are provided for convenience. Models derived from the
official KiCad libraries are distributed under CC BY-SA 4.0 with attribution
to the KiCad Libraries Team.
