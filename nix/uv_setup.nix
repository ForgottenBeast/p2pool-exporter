{
  inputs,
  lib,
  pkgs,
  package_name,
  path_prefix ? "/",
}:
rec {
  # Load a uv workspace from a workspace root.
  # Uv2nix treats all uv projects as workspace projects.
  inherit package_name;
  workspace = inputs.uv2nix.lib.workspace.loadWorkspace {
    workspaceRoot = lib.snowfall.fs.get-file "${path_prefix}${package_name}";
  };

  # Create package overlay from workspace.
  overlay = workspace.mkPyprojectOverlay {
    # Prefer prebuilt binary wheels as a package source.
    # Sdists are less likely to "just work" because of the metadata missing from uv.lock.
    # Binary wheels are more likely to, but may still require overrides for library dependencies.
    sourcePreference = "wheel"; # or sourcePreference = "sdist";
    # Optionally customise PEP 508 environment
    # environ = {
    #   platform_release = "5.10.65";
    # };
  };

  # Extend generated overlay with build fixups
  #
  # Uv2nix can only work with what it has, and uv.lock is missing essential metadata to perform some builds.
  # This is an additional overlay implementing build fixups.
  # See:
  # - https://pyproject-nix.github.io/uv2nix/FAQ.html
  pyprojectOverrides = final: prev: {
    # Implement build fixups here.
    observlib = prev.observlib.overrideAttrs (old: {
      nativeBuildInputs =
        old.nativeBuildInputs
        ++ [ prev.pkgs.python313Packages.setuptools ]
        ++ (final.resolveBuildSystem { setuptools = [ ]; });
    });

  };

  # Use Python 3.12 from nixpkgs
  python = pkgs.python312;

  # Construct package set
  pythonSet =
    # Use base package set from pyproject.nix builders
    (pkgs.callPackage inputs.pyproject-nix.build.packages {
      inherit python;
    }).overrideScope
      (
        lib.composeManyExtensions [
          inputs.pyproject-build-systems.overlays.default
          overlay
          pyprojectOverrides
        ]
      );

}
