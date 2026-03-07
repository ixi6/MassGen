Cloud
=====

Overview
--------

MassGen Cloud allows users to run a MassGen job in the cloud.

Currently, MassGen supports:
- running jobs in the Modal cloud.
- single agent jobs.

Quick Start
-----------
To start using MassGen Cloud, you need to have a Modal account and install the Modal CLI.

.. code-block:: bash

   pip install modal
   modal setup

To run a MassGen job in the cloud, use the ``--cloud`` flag:

.. code-block:: bash

   massgen --cloud --config config.yaml "Your question"

MassGen will upload the config file, context paths, prompt, and any other necessary files to the cloud and run the job there. You can monitor the progress in the local terminal and view the results when the job is complete.

Results and logs will be saved to the local directory ``.massgen/cloud_jobs/job_{job_id}/artifacts/``.