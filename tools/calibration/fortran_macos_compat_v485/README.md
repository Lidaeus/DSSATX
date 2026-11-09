# gfortran strict-format fixes for the official DSSAT v4.8.5.0 tree (tag v4.8.5.0)
# Windows Intel accepts these; gfortran runtime rejects:
# - OPSOILNI.for:139  runtime-built '(T52X,...' -> '(T52,X,...'
# - OPSWBL.for:173    '...I5,1X' + '5(20(F8.4)))' -> comma inserted
# Apply onto a fresh v4.8.5.0 checkout before building .local/build-485-release.
