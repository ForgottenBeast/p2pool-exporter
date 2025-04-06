{
  # Snowfall Lib provides a customized `lib` instance with access to your flake's library
  # as well as the libraries available from your flake's inputs.
  lib,
  # You also have access to your flake's inputs.

  # The namespace used for your flake, defaulting to "internal" if not set.
  namespace,

  # All other arguments come from NixPkgs. You can use `pkgs` to pull shells or helpers
  # programmatically or you may add the named attributes as arguments here.
  pkgs,
  mkShell,
  inputs,
  ...
}:
let
  common = import ./../../uv_setup.nix {
    inherit inputs lib pkgs;
    package_name = namespace;
  };
in

mkShell {
  packages =
    with pkgs;
    [
      python3Packages.bandit
      deadnix
      python312
      pyright
      ruff
      statix
      uv
      vulnix
    ];
  shellHook = ''
    # Undo dependency propagation by nixpkgs.
    unset PYTHONPATH

    # Don't create venv using uv
    export UV_NO_SYNC=1

    # Prevent uv from downloading managed Python's
    export UV_PYTHON_DOWNLOADS=never

    # Get repository root using git. This is expanded at runtime by the editable `.pth` machinery.
    export REPO_ROOT=$(git rev-parse --show-toplevel)
  '';

  env =
    {
      # Prevent uv from managing Python downloads
      UV_PYTHON_DOWNLOADS = "never";
      # Force uv to use nixpkgs Python interpreter
      UV_PYTHON = pkgs.python312;
    }
    // lib.optionalAttrs pkgs.stdenv.isLinux {
      # Python libraries often load native shared objects using dlopen(3).
      # Setting LD_LIBRARY_PATH makes the dynamic library loader aware of libraries without using RPATH for lookup.
      LD_LIBRARY_PATH = lib.makeLibraryPath pkgs.pythonManylinuxPackages.manylinux1;
    };
}
// common
