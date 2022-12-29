import os

import numpy as np
import pandas as pd
import torch

from data_management import IPDataset
from operators import (
    Fourier,
    RadialMaskFunc,
    TVAnalysisPeriodic,
    noise_gaussian,
    to_complex,
    unprep_fft_channel,
)
from reconstruction_methods import admm_l1_rec_diag, grid_search


# ----- load configuration -----
import config  # isort:skip

# ------ setup ----------
device = torch.device("cuda")

file_name = "grid_search_l1_fourier_"
save_path = os.path.join(config.RESULTS_PATH, "grid_search_l1")

# ----- operators --------
mask_func = RadialMaskFunc(config.n, 40)
mask = unprep_fft_channel(mask_func((1, 1) + config.n + (1,)))
OpA = Fourier(mask)
OpTV = TVAnalysisPeriodic(config.n, device=device)

# ----- load test data --------
samples = range(50, 100)
test_data = IPDataset("test", config.DATA_PATH)
X_0 = torch.stack([test_data[s][0] for s in samples])
X_0 = to_complex(X_0.to(device))

# ----- noise setup --------
noise_min = 1e-3
noise_max = 0.08
noise_steps = 2 #original is 50, I dont have the computer power
noise_rel = torch.tensor(
    np.logspace(np.log10(noise_min), np.log10(noise_max), num=noise_steps)
).float()
# add extra noise levels 0.00 and 0.16 for tabular evaluation
noise_rel = (
    torch.cat(
        [torch.zeros(1).float(), noise_rel, 0.16 * torch.ones(1).float()]
    )
    .float()
    .to(device)
)


def meas_noise(y, noise_level):
    return noise_gaussian(y, noise_level)


# ----- set up reconstruction method and grid params --------


def _reconstruct(y, lam, rho):
    x, _ = admm_l1_rec_diag(
        y,
        OpA,
        OpTV,
        OpA.adj(y),
        OpTV(OpA.adj(y)),
        lam,
        rho,
        iter=1000,
        silent=True,
    )
    return x


# parameter search grid
grid_size = 2 #original is 25, I dont have the computing power
grid = {
    "lam": np.logspace(-6, -1, grid_size),
    "rho": np.logspace(-5, 1, grid_size),
}


def combine_results():
    results = pd.DataFrame(
        columns=["noise_rel", "grid_param", "err_min", "grid", "err"]
    )
    for idx in range(len(noise_rel)):
        results_cur = pd.read_pickle(
            os.path.join(save_path, file_name + str(idx) + ".pkl")
        )
        results.loc[idx] = results_cur.loc[idx]

    os.makedirs(save_path, exist_ok=True)
    results.to_pickle(os.path.join(save_path, file_name + "all.pkl"))

    return results


# ------ perform grid search ---------

if __name__ == "__main__":

    #idx_noise = (int(os.environ.get("SGE_TASK_ID")) - 1,) this is for the Sun Grid Engine thing

    for idx in range(len(noise_rel)):

        noise_level = noise_rel[idx] * OpA(X_0).norm(
            p=2, dim=(-2, -1), keepdim=True
        )

        Y_ref = meas_noise(OpA(X_0), noise_level)

        grid_param, err_min, err = grid_search(X_0, Y_ref, _reconstruct, grid)

        results = pd.DataFrame(
            columns=["noise_rel", "grid_param", "err_min", "grid", "err"]
        )

        #print("noise rel", noise_rel[idx])
        #print("grid_param", grid_param)
        #print("err_min:", err_min)
        #print("grid:", grid)
        #print("err:", err)

        results.loc[idx] = {
            "noise_rel": noise_rel[idx].cpu().detach().numpy(),
            "grid_param": grid_param,
            "err_min": err_min.cpu().detach().numpy(),
            "grid": grid,
            "err": err.cpu().detach().numpy(),
        }

        os.makedirs(save_path, exist_ok=True)
        
        results.to_pickle(
            os.path.join(save_path, file_name + str(idx) + ".pkl")
        )

    print(combine_results())
