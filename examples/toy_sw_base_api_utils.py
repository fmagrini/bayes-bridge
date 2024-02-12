from typing import Union
from numbers import Number
import random
import numpy as np
import matplotlib.pyplot as plt

from pysurf96 import surf96
import bayesbay as bb


# -------------- Setting up constants, fwd func, synth data
VP_VS = 1.77
RAYLEIGH_STD = 0.02
LAYERS_MIN = 3
LAYERS_MAX = 15
LAYERS_INIT_RANGE = 0.3
VS_PERTURB_STD = 0.15
VS_UNIFORM_MIN = 2
VS_UNIFORM_MAX = 5
VORONOI_PERTURB_STD = 8
VORONOI_POS_MIN = 0
VORONOI_POS_MAX = 150
N_CHAINS = 2


def _calc_thickness(sites: np.ndarray):
    return bb.discretization.Voronoi1D.compute_cell_extents(np.array(sites, dtype=float))

def _get_thickness(state: bb.State):
    sites = state["voronoi"]["discretization"]
    if state.saved_in_cache("thickness"):
        thickness = state.load_from_cache("thickness")
    else:
        thickness = _calc_thickness(sites)
        state.save_to_cache("thickness", thickness)
    return thickness

def forward_sw(state, periods, wave="rayleigh", mode=1):
    vs = state["voronoi"]["vs"]
    thickness = _get_thickness(state)
    vp = vs * VP_VS
    rho = 0.32 * vp + 0.77
    return surf96(
        thickness,
        vp,
        vs,
        rho,
        periods,
        wave=wave,
        mode=mode,
        velocity="phase",
        flat_earth=False,
    )

true_thickness = np.array([10, 10, 15, 20, 20, 20, 20, 20, 0])
true_voronoi_positions = np.array([5, 15, 25, 45, 65, 85, 105, 125, 145])
true_vs = np.array([3.38, 3.44, 3.66, 4.25, 4.35, 4.32, 4.315, 4.38, 4.5])
true_state = bb.State(
    {
        "voronoi": bb.ParameterSpaceState(
            len(true_vs), 
            {"discretization": true_voronoi_positions, "vs": true_vs}
        )
    }
)

periods1 = np.linspace(4, 80, 20)
rayleigh1 = forward_sw(true_state, periods1, "rayleigh", 1)
rayleigh1_dobs = rayleigh1 + np.random.normal(0, RAYLEIGH_STD, rayleigh1.size)


# -------------- Define bayesbay objects
targets = [
    bb.Target("rayleigh1", rayleigh1_dobs, covariance_mat_inv=1 / RAYLEIGH_STD**2),
]

fwd_functions = [
    (forward_sw, [periods1, "rayleigh", 1]),
]

param_vs = bb.prior.UniformPrior(
    name="vs",
    vmin=VS_UNIFORM_MIN,
    vmax=VS_UNIFORM_MAX,
    perturb_std=VS_PERTURB_STD,
)


def param_vs_initialize(
    param: bb.prior.Prior, 
    positions: Union[np.ndarray, Number]
) -> Union[np.ndarray, Number]: 
    vmin, vmax = param.get_vmin_vmax(positions)
    if isinstance(positions, (float, int)):
        return random.uniform(vmin, vmax)
    sorted_vals = np.sort(np.random.uniform(vmin, vmax, positions.size))
    return sorted_vals


param_vs.set_custom_initialize(param_vs_initialize)
free_parameters = [param_vs]

parameterization = bb.parameterization.Parameterization(
    bb.discretization.Voronoi1D(
        name="voronoi", 
        vmin=VORONOI_POS_MIN, 
        vmax=VORONOI_POS_MAX, 
        perturb_std=VORONOI_PERTURB_STD, 
        n_dimensions=None, 
        n_dimensions_min=LAYERS_MIN, 
        n_dimensions_max=LAYERS_MAX, 
        n_dimensions_init_range=LAYERS_INIT_RANGE, 
        parameters=free_parameters,
        birth_from="prior", 
    )
)


# -------------- Implement log likelihood functions
my_log_likelihood_ratio = bb.LogLikelihood(targets, fwd_functions)


# -------------- Implement perturbation functions
my_perturbation_funcs = parameterization.perturbation_functions


# -------------- Initialize walkers
walkers_start = []
for i in range(N_CHAINS):
    walkers_start.append(parameterization.initialize())

# -------------- Define BayesianInversion
inversion = bb.BaseBayesianInversion(
    walkers_starting_models=walkers_start,
    perturbation_funcs=my_perturbation_funcs,
    log_like_ratio_func=my_log_likelihood_ratio, 
    n_chains=N_CHAINS,
    n_cpus=N_CHAINS,
)
inversion.run(
    n_iterations=50_000,
    burnin_iterations=20_000,
    save_every=100,
    print_every=500,
)

# saving plots, models and targets
saved_states = inversion.get_results(concatenate_chains=True)
interp_depths = np.arange(VORONOI_POS_MAX, dtype=float)
all_thicknesses = [_calc_thickness(m) for m in saved_states["voronoi.discretization"]]

# plot samples, true model and statistics (mean, median, quantiles, etc.)
ax = bb.discretization.Voronoi1D.plot_depth_profiles(
    all_thicknesses, saved_states["voronoi.vs"], linewidth=0.1, color="k"
)
bb.discretization.Voronoi1D.plot_depth_profiles(
    [true_thickness], [true_vs], alpha=1, ax=ax, color="r", label="True"
)
bb.discretization.Voronoi1D.plot_depth_profiles_statistics(
    all_thicknesses, saved_states["voronoi.vs"], interp_depths, ax=ax
)

# plot depths and velocities density profile
fig, axes = plt.subplots(1, 2, figsize=(10, 8))
bb.discretization.Voronoi1D.plot_depth_profile_density(
    all_thicknesses, saved_states["voronoi.vs"], ax=axes[0]
)
bb.discretization.Voronoi1D.plot_interface_hist(
    all_thicknesses, ax=axes[1]
)
for d in np.cumsum(true_thickness):
    axes[1].axhline(d, color="red", linewidth=1)

# saving plots, models and targets
prefix = "toy_sw_base_api_utils"
ax.get_figure().savefig(f"{prefix}_samples")
fig.savefig(f"{prefix}_density")
np.save(f"{prefix}_saved_states", saved_states)
