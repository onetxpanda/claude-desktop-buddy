# Lifted from m5stack/lv_m5_emulator. Wires the PlatformIO native env so
# `pio run -t exec` (or the Execute target) runs the built binary, and so the
# linker gets -m32 if the compiler does. We use this verbatim — no SCons magic
# of our own.
Import("env", "projenv")

for e in [env, projenv]:
    if "-m32" in e["CCFLAGS"]:
        e.Append(LINKFLAGS=["-m32"])

exec_name = "${BUILD_DIR}/${PROGNAME}${PROGSUFFIX}"

from SCons.Script import AlwaysBuild
AlwaysBuild(env.Alias("upload", exec_name, exec_name))

env.AddTarget(
    name="execute",
    dependencies=exec_name,
    actions=exec_name,
    title="Execute",
    description="Build and execute",
    group="General",
)
