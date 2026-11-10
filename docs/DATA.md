# Public Workload Data Traces

This repository uses public workload accounting traces from the Parallel Workloads Archive maintained by the Hebrew University of Jerusalem.

---

## 1. CEA-Curie Trace (CEA-Curie-2011-2.swf.gz)

- **Source URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/index.html`
- **Download URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/CEA-Curie-2011-2.swf.gz`
- **System**: Curie cluster operated by CEA (Commissariat à l'énergie atomique et aux énergies alternatives) for GENCI.
- **Architecture**: Bullx B510 cluster comprising 5,544 nodes and 93,312 compute cores.
- **Trace Duration**: 20 months (February 2011 to October 2012).
- **Header Pragmas**:
  - `Version`: `2.2`
  - `Computer`: `Bullx B510`
  - `Installation`: `CEA Curie Cluster`
  - `Acknowledge`: `Joseph Emeras, CEA/CNRS`
  - `MaxJobs`: `773138`
  - `MaxRecords`: `773138`
  - `UnixStartTime`: `1296571124`
  - `StartTime`: `Tue Feb 01 15:38:44 CET 2011`
  - `EndTime`: `Wed Oct 17 04:25:36 CEST 2012`
  - `TimeZoneString`: `Europe/Paris`
  - `MaxNodes`: `5544`
  - `MaxProcs`: `93312`
  - `Note`: `Scheduler is Slurm (https://computing.llnl.gov/linux/slurm/)`
- **Usage Terms**: Traces from the Parallel Workloads Archive are freely accessible for academic, scientific, and comparative scheduling research. Publications and derivatives should cite the archive and the original trace contributors.

---

## 2. SDSC SP2 Trace (SDSC-SP2-1998-4.2-cln.swf.gz)

- **Source URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/index.html`
- **Download URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/SDSC-SP2-1998-4.2-cln.swf.gz`
- **System**: IBM SP2 supercomputer at the San Diego Supercomputer Center (SDSC).
- **Architecture**: 128 compute nodes with dedicated memory per processor.
- **Trace Duration**: 24 months (April 1998 to April 2000).
- **Header Pragmas**:
  - `Version`: `2.2`
  - `Computer`: `IBM SP2`
  - `Installation`: `SDSC`
  - `Acknowledge`: `Victor Hazlewood`
  - `MaxJobs`: `73496`
  - `MaxRecords`: `59715`
  - `UnixStartTime`: `893466664`
  - `StartTime`: `Fri Apr 24 18:11:04 PDT 1998`
  - `EndTime`: `Sat Apr 29 21:08:32 PDT 2000`
  - `TimeZoneString`: `US/Pacific`
  - `MaxNodes`: `128`
  - `MaxProcs`: `128`
  - `Note`: `THIS IS A CLEANED VERSION OF THE LOG!`
- **Usage Terms**: Freely accessible for research and evaluation purposes with attribution to the San Diego Supercomputer Center and the Parallel Workloads Archive.

---

## 3. Data Storage Rules

- Large downloaded files (`*.swf`, `*.swf.gz`, `*.parquet`) reside in `data/raw/` and are excluded by `data/.gitignore`.
- Tests never access external networks during execution.
- Committed synthetic fixtures in `tests/fixtures/` represent miniature traces used exclusively for unit and integration testing.
