import numpy as np
import matplotlib.pyplot as plt
import bayesbay as bb


# define parameter: Gaussian
gaussian_param = bb.prior.GaussianPrior("gaussian_param", 0, 1, 0.1)

# define parameter space
parameterization = bb.parameterization.Parameterization(
    bb.discretization.Voronoi1D(
        name="my_voronoi", 
        vmin=0, 
        vmax=100, 
        perturb_std=10, 
        n_dimensions=None, 
        n_dimensions_min=1, 
        n_dimensions_max=10, 
        parameters=[gaussian_param], 
    )
)

# define dumb log likelihood
targets = [bb.Target("dumb_data", np.array([1], dtype=float), 1)]
fwd_functions = [lambda _: np.array([1], dtype=float)]

# run the sampler
inversion = bb.BayesianInversion(
    parameterization=parameterization, 
    targets=targets, 
    fwd_functions=fwd_functions, 
    n_chains=1, 
    n_cpus=1, 
)
inversion.run(
    sampler=None, 
    n_iterations=500_000, 
    burnin_iterations=0, 
    save_every=200, 
    print_every=200, 
)

# get results and plot
results = inversion.get_results()
n_dims = results["my_voronoi.n_dimensions"]
sites = results["my_voronoi.discretization"]
param_values = results["gaussian_param"]
fig, axes = plt.subplots(1, 3)
axes[0].hist(n_dims, bins=10, ec="w")
axes[1].hist(np.concatenate(sites), bins=50, ec="w", orientation="horizontal")
axes[2].hist(np.concatenate(param_values), bins=20, ec="w")
fig.savefig("5_prior_voronoi_gaussian_param")
