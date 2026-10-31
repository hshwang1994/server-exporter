#!/bin/bash
# usage: run_abc.sh <envelope root> <out prefix>
E=C:/github/ClovirONE/mock2-fix-20261028/extract; M1="C:/github/서버mock데이터/1차"
T=/c/github/ClovirONE/clovirone-server-gathering/tests/evidence/2026-10-29-redfish-summary-fix/tools
python -I -X utf8 -B $T/summary_abc.py "$1" "$2.json" "$2.md" csus3200_01=$E/csus3200_01 csus3200_02=$E/csus3200_02 csus3200_03=$E/csus3200_03 dl380_gen12_01=$E/dl380_gen12_01 dl380_gen12_02=$E/dl380_gen12_02 dl380_gen12_03=$E/dl380_gen12_03 dl380_gen12_04=$E/dl380_gen12_04 sr650_v4_01=$E/sr650_v4_01 sr650_v4_02=$E/sr650_v4_02 sr650_v4_03=$E/sr650_v4_03 sr650_v4_04=$E/sr650_v4_04 r1_DELL_R740_01="$M1/DELL_R740/01" r1_HPE_CSUS3200_01="$M1/HPE_CSUS3200/01" r1_HPE_CSUS3200_02="$M1/HPE_CSUS3200/02" r1_HPE_CSUS3200_03="$M1/HPE_CSUS3200/03" r1_HPE_CSUS3200_04="$M1/HPE_CSUS3200/04" r1_HPE_DL380_01="$M1/HPE_DL380/01" r1_Lenovo_SR650_01="$M1/Lenovo_SR650/01"
