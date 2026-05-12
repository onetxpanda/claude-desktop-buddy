# Regenerate the DDSM115 4WD-A MuJoCo model from the Waveshare STEP assembly.
#
#   make            # full pipeline: download -> STL -> MJCF
#   make raw        # download the STEP zips
#   make meshes     # tessellate STEP components to STL
#   make model      # generate the MJCF + ascii-named asset STLs
#   make test       # load the model in MuJoCo and run a smoke test
#   make clean

PY ?= python3

RAW_DIR := raw
WHEEL_ZIP := $(RAW_DIR)/DDSM115_STEP.zip
CHASSIS_ZIP := $(RAW_DIR)/DDSM115_4WD-A.zip
CHASSIS_STEP := $(RAW_DIR)/chassis/DDSM115 4WD-A.step

WHEEL_URL := https://files.waveshare.com/upload/c/c9/DDSM115_STEP.zip
CHASSIS_URL := https://files.waveshare.com/upload/2/23/DDSM115_4WD-A.zip

UA := Mozilla/5.0

.PHONY: all raw meshes model test clean

all: model

raw: $(WHEEL_ZIP) $(CHASSIS_ZIP)

$(WHEEL_ZIP):
	@mkdir -p $(RAW_DIR)
	curl -L -A "$(UA)" -o $@ "$(WHEEL_URL)"

$(CHASSIS_ZIP):
	@mkdir -p $(RAW_DIR)
	curl -L -A "$(UA)" -o $@ "$(CHASSIS_URL)"

$(CHASSIS_STEP): $(CHASSIS_ZIP)
	unzip -o -d $(RAW_DIR)/chassis $(CHASSIS_ZIP)
	unzip -o -d $(RAW_DIR)/wheel $(WHEEL_ZIP)
	@touch "$@"

meshes: $(CHASSIS_STEP)
	$(PY) step_to_meshes.py "$(CHASSIS_STEP)" .

model: meshes
	$(PY) build_model.py

test:
	$(PY) -c "import mujoco; m=mujoco.MjModel.from_xml_path('ddsm115_4wd.xml'); \
	d=mujoco.MjData(m); \
	import sys; \
	[mujoco.mj_step(m,d) for _ in range(500)]; \
	print('OK nq=%d nu=%d mass=%.3f' % (m.nq, m.nu, m.body_mass.sum()))"

clean:
	rm -rf assets/ meshes/ assembly.json ddsm115_4wd.xml
