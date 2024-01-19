from bisect import bisect_left
import math
from typing import Tuple, Union, List, Dict, Callable
from numbers import Number
import random
import numpy as np
import matplotlib.pyplot as plt

from ..parameterization._parameter_space import ParameterSpace
from ..perturbations._param_values import ParamPerturbation
from ._discretization import Discretization
from ..exceptions import DimensionalityException
from ..parameters import Parameter
from .._state import State, ParameterSpaceState
from .._utils_1d import (
    interpolate_depth_profile, 
    compute_voronoi1d_cell_extents, 
    insert_scalar,
    nearest_index,
    delete
)


SQRT_TWO_PI = math.sqrt(2 * math.pi)


class Voronoi(Discretization):
    r"""Utility class for Voronoi tessellation

    Parameters
    ----------
    name : str
        name attributed to the Voronoi tessellation, for display and storing 
        purposes
    spatial_dimensions : int
        number of dimensions of the desired Voronoi tessellation, e.g. 1D,
        2D, or 3D.
    vmin, vmax : Union[Number, np.ndarray]
        minimum/maximum value bounding each dimension
    perturb_std : Union[Number, np.ndarray]
        standard deviation of the Gaussians used to randomly perturb the Voronoi
        sites in each dimension. 
    n_dimensions : Number, optional
        number of dimensions. None (default) results in a trans-dimensional
        discretization, with the dimensionality of the parameter space allowed
        to vary in the range ``n_dimensions_min``-``n_dimensions_max``
    n_dimensions_min, n_dimensions_max : Number, optional
        minimum and maximum number of dimensions, by default 1 and 10. These
        parameters are ignored if ``n_dimensions`` is not None, i.e. if the
        discretization is not trans-dimensional
    n_dimensions_init_range : Number, optional
        percentage of the range `n_dimensions_min`` - ``n_dimensions_max`` used to
        initialize the number of dimensions (0.3. by default). For example, if 
        ``n_dimensions_min`` = 1, ``n_dimensions_max`` = 10, and 
        ``n_dimensions_init_range`` = 0.5,
        the maximum number of dimensions at the initialization is
            
            int((n_dimensions_max - n_dimensions_min) * n_dimensions_init_range + n_dimensions_max)
            
    parameters : List[Parameter], optional
        a list of free parameters, by default None
    birth_from : {"prior", "neighbour"}, optional
        whether to initialize the free parameters associated with the newborn 
        Voronoi cell by randomly drawing from their prior or by perturbing the 
        value found in the nearest Voronoi cell (default).
    """
    def __init__(
        self,
        name: str,
        spatial_dimensions: Number,
        vmin: Union[Number, np.ndarray],
        vmax: Union[Number, np.ndarray],
        perturb_std: Union[Number, np.ndarray],
        n_dimensions: int = None, 
        n_dimensions_min: int = 1, 
        n_dimensions_max: int = 10, 
        n_dimensions_init_range: Number = 0.3, 
        parameters: List[Parameter] = None, 
        birth_from: str = "neighbour",  # either "neighbour" or "prior"
    ):
        super().__init__(
            name=name,
            spatial_dimensions=spatial_dimensions,
            perturb_std=perturb_std,
            n_dimensions=n_dimensions,
            n_dimensions_min=n_dimensions_min,
            n_dimensions_max=n_dimensions_max,
            n_dimensions_init_range=n_dimensions_init_range,
            parameters=parameters,
            birth_from=birth_from,
            vmin=vmin,
            vmax=vmax
        )
        self.vmin = vmin
        self.vmax = vmax
        msg = "The %s number of Voronoi cells, "
        if n_dimensions is not None:
            assert n_dimensions > 0, msg % "minimum" + "`n_dimensions`, should be greater than zero"
            assert isinstance(n_dimensions, int), msg % "minimum" + "`n_dimensions`, should be an integer"
            assert isinstance(n_dimensions, int), msg % "maximum" + "`n_dimensions`, should be an integer"
            
    def log_prior(self, *args):
        r"""
        BayesBay implements the grid trick, which calculates the prior 
        probability of a Voronoi discretization through the combinatorial 
        formula :math:`{N \choose k}^{-1}`, with `k` denoting the number of 
        Voronoi sites and `N` the number of possible positions allowed for the 
        sites [3]_.
        
        References
        ----------
        .. [3] Bodin and Sambridge (2009), Seismic tomography with the reversible 
            jump algorithm
        """
        raise NotImplementedError

    def _init_perturbation_funcs(self):
        ParameterSpace._init_perturbation_funcs(self)
        self._perturbation_funcs.append(ParamPerturbation(self.name, [self]))

    @property
    def perturbation_functions(self) -> List[Callable[[State], Tuple[State, Number]]]:
        r"""the list of perturbation functions allowed in the parameter space linked to
        the Voronoi discretization. Each function takes in a state (see :class:`State`) 
        and returns a new state along with the corresponding partial acceptance 
        probability,
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}},

        """
        return self._perturbation_funcs


class Voronoi1D(Voronoi):
    r"""Utility class for Voronoi tessellation in 1D

    Parameters
    ----------
    name : str
        name attributed to the Voronoi tessellation, for display and storing 
        purposes
    vmin, vmax : Union[Number, np.ndarray]
        minimum/maximum value bounding each dimension
    perturb_std : Union[Number, np.ndarray]
        standard deviation of the Gaussians used to randomly perturb the Voronoi
        sites in each dimension. 
    n_dimensions : Number, optional
        number of dimensions. None (default) results in a trans-dimensional
        discretization, with the dimensionality of the parameter space allowed
        to vary in the range ``n_dimensions_min``-``n_dimensions_max``
    n_dimensions_min, n_dimensions_max : Number, optional
        minimum and maximum number of dimensions, by default 1 and 10. These
        parameters are ignored if ``n_dimensions`` is not None, i.e. if the
        discretization is not trans-dimensional
    n_dimensions_init_range : Number, optional
        percentage of the range ``n_dimensions_min`` - ``n_dimensions_max`` used to
        initialize the number of dimensions (0.3. by default). For example, if 
        ``n_dimensions_min`` = 1, ``n_dimensions_max`` = 10, and 
        ``n_dimensions_init_range`` = 0.5,
        the maximum number of dimensions at the initialization is::
            
            int((n_dimensions_max - n_dimensions_min) * n_dimensions_init_range + n_dimensions_max)
            
    parameters : List[Parameter], optional
        a list of free parameters, by default None
    birth_from : {"prior", "neighbour"}, optional
        whether to initialize the free parameters associated with the newborn 
        Voronoi cell by randomly drawing from their prior or by perturbing the 
        value found in the nearest Voronoi cell (default).
    """
    def __init__(        
            self,
            name: str,
            vmin: Number,
            vmax: Number,
            perturb_std: Union[Number, np.ndarray],
            n_dimensions: int = None, 
            n_dimensions_min: int = 1, 
            n_dimensions_max: int = 10, 
            n_dimensions_init_range: Number = 0.3, 
            parameters: List[Parameter] = None, 
            birth_from: str = "neighbour"  # either "neighbour" or "prior"
        ): 
        super().__init__(
            name=name,
            spatial_dimensions=1,
            vmin=vmin,
            vmax=vmax,
            perturb_std=perturb_std,
            n_dimensions=n_dimensions,
            n_dimensions_min=n_dimensions_min,
            n_dimensions_max=n_dimensions_max,
            n_dimensions_init_range=n_dimensions_init_range,
            parameters=parameters,
            birth_from=birth_from
        )
    
    def initialize(self) -> ParameterSpaceState:
        """initializes the parameter space linked to the Voronoi tessellation

        Returns
        -------
        ParameterSpaceState
            an initial parameter space state
        """
        # initialize number of dimensions
        if not self.trans_d:
            n_voronoi_cells = self._n_dimensions
        else:
            init_range = self._n_dimensions_init_range
            n_dims_min = self._n_dimensions_min
            n_dims_max = self._n_dimensions_max
            init_max = int((n_dims_max - n_dims_min) * init_range + n_dims_min)
            n_voronoi_cells = random.randint(n_dims_min, init_max)
        lb, ub = self.vmin, self.vmax
        voronoi_sites = np.sort(np.random.uniform(lb, ub, n_voronoi_cells))

        # initialize parameter values
        parameter_vals = {"discretization": voronoi_sites}
        for name, param in self.parameters.items():
            parameter_vals[name] = param.initialize(voronoi_sites)
        return ParameterSpaceState(n_voronoi_cells, parameter_vals)    
    
    def _perturb_site(self, site: Number) -> Number:
        """perturbes a Voronoi  site
        
        Parameters
        ----------
        site : float
            Voronoi site position

        Returns
        -------
        Number
            perturbed Voronoi site position
        """        
        while True:
            random_deviate = random.normalvariate(0, self.perturb_std)
            new_site = site + random_deviate
            if new_site >= self.vmin and new_site <= self.vmax:
                return new_site   
        
    def perturb_value(self, old_ps_state: ParameterSpaceState, isite: Number):
        r"""perturbs the value of one Voronoi site and calculates the log of the
        partial acceptance probability
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}}.

        Parameters
        ----------
        old_ps_state : ParameterSpaceState
            the current parameter space state
        isite : Number
            the index of the Voronoi site to be perturbed

        Returns
        -------
        Tuple[ParameterSpaceState, Number]
            the new parameter space state and its associated partial acceptance 
            probability excluding log likelihood ratio
        """
        old_sites = old_ps_state["discretization"]
        old_site = old_sites[isite]
        new_site = self._perturb_site(old_sites[isite])
        new_sites = old_sites.copy()
        new_sites[isite] = new_site
        isort = np.argsort(new_sites)
        new_sites = new_sites[isort]
        new_values = {"discretization": new_sites}
        log_prior_ratio = 0
        for param_name, param in self.parameters.items():
            values = old_ps_state[param_name]
            if param.position is not None:
                log_prior_old = param.log_prior(values[isite], old_site)
                log_prior_new = param.log_prior(values[isite], new_site)
                log_prior_ratio += log_prior_new - log_prior_old
            new_values[param_name] = values[isort]
            
        new_ps_state = ParameterSpaceState(old_ps_state.n_dimensions, new_values)
        return new_ps_state, log_prior_ratio # log_proposal_ratio=0 and log_det_jacobian=0
        
    def _initialize_newborn_params(
            self, 
            new_site: Number, 
            old_sites: np.ndarray, 
            param_space_state: ParameterSpaceState
            ):
        """initialize the parameter values in the newborn dimension
    
        Parameters
        ----------
        new_site : Number
            position of the newborn Voronoi site
        old_sites : np.ndarray
            all positions of the current Voronoi sites
        param_space_state : ParameterSpaceState
            current parameter space state
    
        Returns
        -------
        Dict[str, float]
            key value pairs that map parameter names to values of the ``new_site``
        """
        if self.birth_from == 'prior':
            return self._initialize_params_from_prior(
                new_site, old_sites, param_space_state
                )
        return self._initialize_params_from_neighbour(
            new_site, old_sites, param_space_state
            )
    
    def _initialize_params_from_prior(
            self, 
            new_site: Number, 
            old_sites: np.ndarray, 
            param_space_state: ParameterSpaceState
            ) -> Tuple[Dict[str, np.ndarray], None]:
        """initialize the newborn dimension by randomly drawing parameter values
        from the prior
    
        Parameters
        ----------
        new_site : Number
            position of the newborn Voronoi site
        old_sites : np.ndarray
            all positions of the current Voronoi sites
        param_space_state : ParameterSpaceState
            current parameter space state
    
        Returns
        -------
        Tuple[Dict[str, np.ndarray], None]
            key value pairs that map parameter names to values of the ``new_site``
        """
        new_born_values = dict()
        for param_name, param in self.parameters.items():
            new_value = param.initialize(new_site)
            new_born_values[param_name] = new_value
        return new_born_values, None
    
    def _initialize_params_from_neighbour(
        self, 
        new_site: Number, 
        old_sites: np.ndarray, 
        param_space_state: ParameterSpaceState
        ) -> Tuple[Dict[str, np.ndarray], Number]:
        """initialize the newborn parameter values by perturbing the nearest 
        Voronoi cell
    
        Parameters
        ----------
        new_site : Number
            position of the newborn Voronoi cell
        old_sites : np.ndarray
            all positions of the current Voronoi cells
        param_space_state : ParameterSpaceState
            current parameter space state
    
        Returns
        -------
        Tuple[Dict[str, np.ndarray], Number]
            key value pairs that map parameter names to values of the ``new_site``
            and the index of the Voronoi neighbour
        """
        isite = nearest_index(xp=new_site, x=old_sites, xlen=old_sites.size)
        new_born_values = dict()
        for param_name, param in self.parameters.items():
            old_values = param_space_state[param_name]
            new_value, _ = param.perturb_value(old_values[isite], new_site)
            new_born_values[param_name] = new_value
        return new_born_values, isite
    
    def _log_probability_ratio_birth(
            self, 
            old_isite: Number, 
            old_ps_state: ParameterSpaceState, 
            new_isite: Number, 
            new_ps_state: ParameterSpaceState
            ):
        if self.birth_from == 'prior':
            return 0
        return self._log_probability_ratio_birth_from_neighbour(
            old_isite, old_ps_state, new_isite, new_ps_state
        )
    
    def _log_probability_ratio_birth_from_neighbour(
            self, 
            old_isite: Number, 
            old_ps_state: ParameterSpaceState, 
            new_isite: Number, 
            new_ps_state: ParameterSpaceState
    ):
        old_site = old_ps_state["discretization"][old_isite]
        new_site = new_ps_state["discretization"][new_isite]
        log_prior_ratio = 0
        log_proposal_ratio = 0
        for param_name, param in self.parameters.items():
            new_value = new_ps_state[param_name][new_isite]
            log_prior_ratio += param.log_prior(new_value, new_site)
            
            old_value = old_ps_state[param_name][old_isite]
            perturb_std = param.get_perturb_std(old_site)
            log_proposal_ratio += (
                math.log(perturb_std * SQRT_TWO_PI)
                + (new_value - old_value) ** 2 / (2 * perturb_std**2)
            )
        return log_prior_ratio + log_proposal_ratio # log_det_jacobian is 1          
    
    def birth(self, old_ps_state: ParameterSpaceState) -> Tuple[ParameterSpaceState, float]:
        r"""creates a new Voronoi cell, initializes all free parameters 
        associated with it, and returns the pertubed state along with the
        log of the corresponding partial acceptance probability,
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}}.
    
        In this case, the prior probability of the model :math:`{\bf m}` is
        
        .. math::
            p({\bf m}) = p({\bf c} \mid k) p(k) \prod_i{p({\bf v}_i \mid {\bf c})} ,
        
        where :math:`k` denotes the number of Voronoi cells, each entry of the 
        vector :math:`{\bf c}` corresponds to the position of a Voronoi site, 
        and each :math:`i`\ th free parameter :math:`{\bf v}` has the same 
        dimensionality as :math:`{\bf c}`. 
        
        Following [1]_, :math:`p({\bf c} \mid k) = \frac{k! \left(N - k \right)!}{N!}`. If we then
        assume that :math:`p(k) = \frac{1}{\Delta k}`, where :math:`\Delta k = k_{max} - k_{min}`,
        the prior ratio reads
        
        .. math::
            \frac{p({\bf m'})}{p({\bf m})} = 
            \frac{(k+1) \prod_i p(v_i^{k+1})}{(N-k)},
                                         
        where :math:`p(v_i^{k+1})` denotes the prior probability of the newly
        born :math:`i`\ th parameter, which may be dependent on :math:`{\bf c}`.
        The proposal ratio reads
        
        .. math::
            \frac{q({\bf m} \mid {\bf m'})}{q({\bf m'} \mid {\bf m})} =
            \frac{(N-k)}{(k+1) \prod_i q_{v_i}^{k+1}},
                         
        where :math:`q_{v_i}^{k+1}` denotes the proposal probability for the
        newly born :math:`i`\ th parameter in the new dimension. It is easy to
        show that, in the case of a birth from neighbor [1]_ or a birth from
        prior [2]_ (see :attr:`birth_from`), :math:`\lvert \mathbf{J} \rvert = 1`
        and :math:`\alpha_{p} = \frac{p({\bf m'})}{p({\bf m})} \frac{q({\bf m} \mid {\bf m'})}{q({\bf m'} \mid {\bf m})}`. 
        It follows that
        
        .. math::
            \alpha_{p} = 
            \frac{(k+1) \prod_i p(v_i^{k+1})}{(N-k)} \frac{(N-k)}{(k+1) \prod_i q_{v_i}^{k+1}} = 
            \frac{\prod_i p(v_i^{k+1})}{\prod_i{q_{v_i}^{k+1}}}.
            
        In the case of a birth from prior, :math:`q_{v_i}^{k+1} = p(v_i^{k+1})`
        and
        
        .. math::
            \alpha_{p} = 
            \frac{\prod_i p(v_i^{k+1})}{\prod_i{p(v_i^{k+1})}} = 1.
                                                                  
        In the case of a birth from neighbor, :math:`q_{v_i}^{k+1} = 
        \frac{1}{\theta \sqrt{2 \pi}} \exp \lbrace -\frac{\left( v_i^{k+1} - v_i \right)^2}{2\theta^2} \rbrace`,
        where the newly born value, :math:`v_i^{k+1}`, is generated by perturbing
        the original value, :math:`v_i`, of the :math:`i`\ th parameter. This is 
        achieved through a random deviate from the normal distribution 
        :math:`\mathcal{N}(v_i, \theta)`, with :math:`\theta` denoting the 
        standard deviation of the Gaussian used to carry out the perturbation
        (see, for example, :attr:`bayesbay.parameters.UniformParameter.perturb_std`) . 
        The partial acceptance probability is then computed numerically.
                  
    
        Parameters
        ----------
        old_ps_state : ParameterSpaceState
            current parameter space state
    
        Returns
        -------
        ParameterSpaceState
            new parameter space state
        Number
            log of the partial acceptance probability, 
            :math:`log(\alpha_{p}) = \log(\frac{\prod_i p(v_i^{k+1})}{\prod_i{q_{v_i}^{k+1}}})`
            
        References
        ----------
        .. [1] Bodin et al. 2012, Transdimensional inversion of receiver functions 
            and surface wave dispersion
        .. [2] Hawkins and Sambridge 2015, Geophysical imaging using trans-dimensional 
            trees
        """
        # prepare for birth perturbation
        n_cells = old_ps_state.n_dimensions
        if n_cells == self._n_dimensions_max:
            raise DimensionalityException("Birth")
        # randomly choose a new Voronoi site position
        lb, ub = self.vmin, self.vmax
        new_site = random.uniform(lb, ub)
        old_sites = old_ps_state["discretization"]
        unsorted_values, i_nearest = self._initialize_newborn_params(
            new_site, old_sites, old_ps_state
        )
        new_values = dict()
        idx_insert = bisect_left(old_sites, new_site)
        new_sites = insert_scalar(old_sites, idx_insert, new_site)
        new_values["discretization"] = new_sites
        for name, value in unsorted_values.items():
            old_values = old_ps_state[name]
            new_values[name] = insert_scalar(old_values, idx_insert, value)
        new_ps_state = ParameterSpaceState(n_cells + 1, new_values)
        return new_ps_state, self._log_probability_ratio_birth(
            i_nearest, old_ps_state, idx_insert, new_ps_state
        )
    
    def _log_probability_ratio_death(
            self, 
            iremove: Number, 
            old_ps_state: ParameterSpaceState, 
            new_ps_state: ParameterSpaceState
            ):
        if self.birth_from == 'prior':
            return 0
        return self._log_probability_ratio_death_from_neighbour(
            iremove, old_ps_state, new_ps_state
        )
    
    def _log_probability_ratio_death_from_neighbour(
            self, 
            iremove: Number, 
            old_ps_state: ParameterSpaceState, 
            new_ps_state: ParameterSpaceState
            ):
        old_sites = old_ps_state["discretization"]
        new_sites = new_ps_state["discretization"]
        i_nearest = nearest_index(
            xp=old_sites[iremove], x=new_sites, xlen=new_sites.size
        )
        return -self._log_probability_ratio_birth(
            i_nearest, new_ps_state, iremove, old_ps_state
        )

    def death(self, old_ps_state: ParameterSpaceState):
        r"""removes a new Voronoi cell and returns the pertubed state along with 
        the log of the corresponding partial acceptance probability,
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}}.
    
        It is straightforward to show that this equals the reciprocal of
        the partial acceptance probability obtained in the case of a birth
        perturbation (see :meth:`birth`), i.e.,
                
        .. math::
            \alpha_{p} = \frac{\prod_i{q_{v_i}^{k+1}}}{\prod_i p(v_i^{k+1})}.
    
        Parameters
        ----------
        old_ps_state : ParameterSpaceState
            current parameter space state
    
        Returns
        -------
        ParameterSpaceState
            new parameter space state
        Number
            log of the partial acceptance probability, 
            :math:`log(\alpha_{p}) = -\log(\frac{\prod_i p(v_i^{k+1})}{\prod_i{q_{v_i}^{k+1}}})`
        """
        # prepare for death perturbation
        n_cells = old_ps_state.n_dimensions
        if n_cells == self._n_dimensions_min:
            raise DimensionalityException("Death")
        # randomly choose an existing Voronoi site to kill
        iremove = random.randint(0, n_cells - 1)
        # remove parameter values for the removed site
        new_values = dict()
        for name, old_values in old_ps_state.param_values.items():
            new_values[name] = delete(old_values, iremove)
        new_ps_state = ParameterSpaceState(n_cells - 1, new_values) 
        return new_ps_state, self._log_probability_ratio_death(
            iremove, old_ps_state, new_ps_state
        )
    
    @staticmethod
    def compute_cell_extents(voronoi_sites: np.ndarray, lb=0, ub=-1, fill_value=0):
        r"""compute Voronoi cell extents from the Voronoi sites. Voronoi-cell
        boundaries are first drawn at the midpoint between consecutive Voronoi
        nuclei. The extent is then derived from the distance between consecutive
        boundaries.

        Parameters
        ----------
        voronoi_sites : np.ndarray of shape (n,)
            Voronoi-site positions. These should be greater or equal to zero

        lb, ub : float
            Lower and upper bounds used in the calculation of Voronoi-cell
            extents. Negative values for `lb` or `ub` denote an unbounded cell.
            The extent of an unbounded cell is set to `fill_value`

        fill_value : float
            Value attributed to unbounded Voronoi cells

        Returns
        -------
        np.ndarray
            Voronoi-cell extents

        Examples
        --------
        >>> depth = np.array([2, 5.5, 8, 10])

        >>> Voronoi1D.compute_cell_extents(depth, lb=0, ub=-1, fill_value=np.nan)
        array([3.75, 3.  , 2.25,  nan])

        >>> Voronoi1D.compute_cell_extents(depth, lb=-1, ub=-1, fill_value=np.nan)
        array([ nan, 3.  , 2.25,  nan])

        >>> Voronoi1D.compute_cell_extents(depth, lb=0, ub=15, fill_value=np.nan)
        array([3.75, 3.  , 2.25, 6.  ])
        """
        return compute_voronoi1d_cell_extents(
            voronoi_sites, lb=lb, ub=ub, fill_value=fill_value
        )

    @staticmethod
    def plot_depth_profiles_density(
        samples_voronoi_cell_extents: np.ndarray,
        samples_param_values: np.ndarray,
        depths_bins: Union[int, np.ndarray] = 100, 
        param_values_bins: Union[int, np.ndarray] = 100,
        ax=None,
        **kwargs,
    ):
        """plot a 2D histogram of parameter values density at refined depth positions

        Parameters
        ----------
        samples_voronoi_cell_extents : ndarray
            A 2D numpy array where each row represents a sample of thicknesses (or
            Voronoi cell extents)
        samples_param_values : ndarray
            A 2D numpy array where each row represents a sample of parameter values
            (e.g., velocities)
        depths_bins: int or np.ndarray, optional
            The depth bins or their number, default to 100
        param_values_bins: int or np.ndarray, optional
            The parameter value bins or their number, default to 100
        ax : Axes, optional
            An optional Axes object to plot on
        kwargs : dict, optional
            Additional keyword arguments to pass to ax.hist2d

        Returns
        -------
        ax : Axes
            The Axes object containing the plot
        
        Examples
        --------
        .. code-block:: python
        
            from bayesbay.discretization import Voronoi1D
            
            # define and run the Bayesian inversion
            ...
            
            # plot
            results = inversion.get_results()
            samples_voronoi_cell_extents = [
                Voronoi1D.compute_cell_extents(d) for d in results["my_voronoi.discretization"]
            ]
            samples_param_values = results["vs"]
            ax = Voronoi1D.plot_depth_profiles_density(
                samples_voronoi_cell_extents, samples_param_values
            )
        """
        if ax is None:
            _, ax = plt.subplots()
        
        if isinstance(depths_bins, int):
            depths = []
            for cell_extents in samples_voronoi_cell_extents:
                depths.extend(np.cumsum(np.array(cell_extents)))
            depth_max = np.max(depths)
            depth_min = 0
            new_depths = np.linspace(depth_min, depth_max, depths_bins)
        elif isinstance(depths_bins, np.ndarray):
            new_depths = depths_bins
        else:
            raise TypeError("depths_bins should be either an int or np.ndarray")

        new_param_values = Voronoi1D._interpolate_depth_profiles(
            samples_voronoi_cell_extents, samples_param_values, new_depths
        )
        
        # plotting the 2D histogram
        cax = ax.hist2d(
            new_param_values.ravel(), 
            np.tile(new_depths, new_param_values.shape[0]), 
            bins=(param_values_bins, len(new_depths)), 
            **kwargs
        )
        # colorbar (for the histogram density)
        cbar = plt.colorbar(cax[3], ax=ax)
        cbar.set_label("Density")
        if ax.get_ylim()[0] < ax.get_ylim()[1]:
            ax.invert_yaxis()
        ax.set_xlabel("Parameter values")
        ax.set_ylabel("Depth")
        return ax

    @staticmethod
    def plot_interface_hist(
        samples_voronoi_cell_extents,
        bins=100,
        ax=None,
        **kwargs,
    ):
        """plot the 1D depth histogram of interfaces

        Parameters
        ----------
        samples_voronoi_cell_extents : list
            a list of voronoi cell extents (thicknesses in the 1D case)
        bins : int, optional
            number of vertical bins, by default 100
        ax : matplotlib.axes.Axes, optional
            an optional user-provided ax, by default None

        Returns
        -------
        matplotlib.axes.Axes
            the resulting plot that has the depth distribution on it
        """
        if ax is None:
            _, ax = plt.subplots()
        depths = []
        for thicknesses in samples_voronoi_cell_extents:
            depths.extend(np.cumsum(thicknesses))
        # calculate 1D histogram
        h, e = np.histogram(depths, bins=bins, density=True)
        # plot the histogram
        ax.barh(e[:-1], h, height=np.diff(e), align="edge", label="histogram", **kwargs)
        if ax.get_ylim()[0] < ax.get_ylim()[1]:
            ax.invert_yaxis()
        ax.set_xlabel("Number of interfaces")
        ax.set_ylabel("Depth")
        return ax

    @staticmethod
    def plot_depth_profiles(
        samples_voronoi_cell_extents: list,
        samples_param_values: list,
        ax=None,
        **kwargs,
    ):
        """plot multiple 1D Earth models based on sampled parameters.

        Parameters
        ----------
        samples_voronoi_cell_extents : list
            a list of voronoi cell extents (thicknesses in the 1D case)
        samples_param_values : ndarray
            a 2D numpy array where each row represents a sample of parameter values
            (e.g., velocities)
        ax : Axes, optional
            an optional Axes object to plot on
        kwargs : dict, optional
            additional keyword arguments to pass to ax.step

        Returns
        -------
        ax : Axes
            The Axes object containing the plot
        """
        if ax is None:
            _, ax = plt.subplots()

        # Default plotting style for samples
        sample_style = {
            "linewidth": kwargs.pop("linewidth", kwargs.pop("lw", 0.5)),
            "alpha": 0.2,
            "color": kwargs.pop(
                "color", kwargs.pop("c", "blue")
            ),  # Fixed color for the sample lines
        }
        sample_style.update(kwargs)  # Override with any provided kwargs

        for thicknesses, values in zip(
            samples_voronoi_cell_extents, samples_param_values
        ):
            thicknesses = np.insert(thicknesses[:-1], -1, 20)
            y = np.insert(np.cumsum(thicknesses), 0, 0)
            x = np.insert(values, 0, values[0])
            ax.step(x, y, where="post", **sample_style)

        if ax.get_ylim()[0] < ax.get_ylim()[1]:
            ax.invert_yaxis()
        ax.set_xlabel("Parameter values")
        ax.set_ylabel("Depth")

        return ax
    
    def interpolate_depth_profile(
        voronoi_cell_extents, param_values, interp_positions
    ):
        """interpolates the values of a physical parameter that is a function of depth
        as defined by the Voronoi discretization onto the specified depth positions

        Parameters
        ----------
        voronoi_cell_extents : np.ndarray
            the extent of each Voronoi cell
        param_values : np.ndarray
            the physical parameter value associated with each Voronoi cell
        interp_positions : np.ndarray
            the depths at which the parameter values will be returned

        Returns
        -------
        np.ndarray
            the physical parameter values associated with ``interp_positions``
        """ 
        return interpolate_depth_profile(
            np.array(voronoi_cell_extents),
            np.array(param_values), 
            interp_positions, 
        )

    @staticmethod
    def _interpolate_depth_profiles(
        samples_voronoi_cell_extents, samples_param_values, interp_positions
    ):
        interp_params = np.zeros((len(samples_param_values), len(interp_positions)))
        for i, (sample_extents, sample_values) in enumerate(
            zip(samples_voronoi_cell_extents, samples_param_values)
        ):
            interp_params[i, :] = interpolate_depth_profile(
                np.array(sample_extents), np.array(sample_values), interp_positions
            )
        return interp_params

    @staticmethod
    def get_depth_profiles_statistics(
        samples_voronoi_cell_extents: list,
        samples_param_values: list,
        interp_positions: np.ndarray,
        percentiles: tuple = (10, 90),
    ) -> dict:
        """get the mean, median, std and percentiles of the given ensemble

        Parameters
        ----------
        samples_voronoi_cell_extents : list
            a list of voronoi cell extents (thicknesses in the 1D case)
        samples_param_values : list
            a list of physical parameter values to draw statistics from
        interp_positions : np.ndarray
            points to interpolate
        percentiles : tuple, optional
            percentiles to calculate, by default (10, 90)

        Returns
        -------
        dict
            a dictionary with these keys: "mean", "median", "std" and "percentile"
        """
        interp_params = Voronoi1D._interpolate_depth_profiles(
            samples_voronoi_cell_extents, samples_param_values, interp_positions
        )
        statistics = {
            "mean": np.mean(interp_params, axis=0),
            "median": np.median(interp_params, axis=0),
            "std": np.std(interp_params, axis=0),
            "percentiles": np.percentile(interp_params, percentiles, axis=0),
        }
        return statistics

    @staticmethod
    def plot_depth_profiles_statistics(
        samples_voronoi_cell_extents: list,
        samples_param_values: list,
        interp_positions: np.ndarray,
        percentiles=(10, 90),
        ax=None,
    ):
        """plot the mean, median, std and percentiles from the given samples

        Parameters
        ----------
        samples_voronoi_cell_extents : list
            a list of voronoi cell extents (thicknesses in the 1D case)
        samples_param_values : list
            a list of physical parameter values to draw statistics from
        interp_positions : _type_
            points to interpolate
        percentiles : tuple, optional
            percentiles to calculate, by default (10, 90)
        ax : matplotlib.axes.Axes, optional
            an optional user-provided ax, by default None

        Returns
        -------
        matplotlib.axes.Axes
            the resulting plot that has the statistics on it
        """
        statistics = Voronoi1D.get_depth_profiles_statistics(
            samples_voronoi_cell_extents,
            samples_param_values,
            interp_positions,
            percentiles,
        )
        mean = statistics["mean"]
        std = statistics["std"]
        percentiles = statistics["percentiles"]
        if ax is None:
            _, ax = plt.subplots()
        ax.plot(mean, interp_positions, color="b", label="Mean")
        ax.plot(mean - std, interp_positions, "b--")
        ax.plot(mean + std, interp_positions, "b--")
        ax.plot(statistics["median"], interp_positions, color="orange", label="Median")
        ax.plot(
            percentiles[0],
            interp_positions,
            color="orange",
            ls="--",
        )
        ax.plot(
            percentiles[1],
            interp_positions,
            color="orange",
            ls="--",
        )
        ax.legend()
        return ax