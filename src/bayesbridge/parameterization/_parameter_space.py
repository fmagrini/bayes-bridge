from typing import List, Callable, Tuple, Dict
from numbers import Number
import random
import numpy as np

from .._state import State, ParameterSpaceState
from ..exceptions import DimensionalityException
from ..parameters import Parameter
from ..perturbations._param_values import ParamPerturbation
from ..perturbations._birth_death import BirthPerturbation, DeathPerturbation
from .._utils_1d import delete, insert_scalar


class ParameterSpace:
    r"""Utility class to parameterize the Bayesian inference problem
    
    Parameters
    ----------
    name : str
        name of the parameter space, for display and storing purposes
    n_dimensions : Number, optional
        number of dimensions defining the parameter space. None (default) results 
        in a trans-dimensional space.
    n_dimensions_min, n_dimensions_max : Number, optional
        minimum and maximum number of dimensions, by default 1 and 10. These
        parameters are ignored if ``n_dimensions`` is not None, i.e. if the
        parameter space is not trans-dimensional
    n_dimensions_init_range : Number, optional
        percentage of the range `n_dimensions_min`-`n_dimensions_max` used to
        initialize the number of dimensions (0.3. by default). For example, if 
        `n_dimensions_min`=1, `n_dimensions_max`=10, and `n_dimensions_init_range`=0.5,
        the maximum number of dimensions at the initialization is
        
        .. code-block:: python
            
            int((n_dimensions_max - n_dimensions_min) * n_dimensions_init_range + n_dimensions_max)
            
    parameters : List[Parameter], optional
        a list of free parameters, by default None
    """
    def __init__(
        self, 
        name: str,
        n_dimensions: int = None, 
        n_dimensions_min: int = 1, 
        n_dimensions_max: int = 10, 
        n_dimensions_init_range: Number = 0.3, 
        parameters: List[Parameter] = None, 
    ):
        self._name = name
        self._trans_d = n_dimensions is None
        self._n_dimensions = n_dimensions
        self._n_dimensions_min = n_dimensions_min if self._trans_d else n_dimensions
        self._n_dimensions_max = n_dimensions_max if self._trans_d else n_dimensions
        self._n_dimensions_init_range = n_dimensions_init_range
        self._parameters = dict()
        if parameters is not None:
            for param in parameters:
                self._parameters[param.name] = param
        self._init_perturbation_funcs()
    
    @property
    def name(self) -> str:
        """name of the parameter space"""
        return self._name
    
    @property
    def trans_d(self) -> bool:
        """indicates whether the current configuration allows changes in 
        dimensionality
        """
        return self._trans_d
    
    @property
    def parameters(self) -> Dict[str, Parameter]:
        """all the free parameters defined in this parameter space"""
        return self._parameters
    
    @property
    def perturbation_functions(self) -> List[Callable[[State], Tuple[State, Number]]]:
        r"""a list of perturbation functions allowed in the current parameter space, 
        each of which takes in a state (see :class:`State`) and returns a new
        state and the corresponding partial acceptance probability,
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}},

        """
        return self._perturbation_funcs
    
    def initialize(self) -> ParameterSpaceState:
        """initializes the parameter space including its parameter values

        Returns
        -------
        ParameterSpaceState
            an initial parameter space state
        """
        # initialize number of dimensions
        if not self.trans_d:
            n_dimensions = self._n_dimensions
        else:
            init_range = self._n_dimensions_init_range
            n_dims_min = self._n_dimensions_min
            n_dims_max = self._n_dimensions_max
            init_max = int((n_dims_max - n_dims_min) * init_range + n_dims_min)
            n_dimensions = random.randint(n_dims_min, init_max)
        # initialize parameter values
        parameter_vals = dict()
        for name, param in self.parameters.items():
            parameter_vals[name] = param.initialize(np.empty(n_dimensions))
        return ParameterSpaceState(n_dimensions, parameter_vals)
    
    def birth(self, ps_state: ParameterSpaceState) -> Tuple[ParameterSpaceState, float]:
        r"""adds a dimension to the current parameter space and returns the
        thus obtained new state along with the log of the corresponding partial 
        acceptance probability,
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}}.
            
        In this case, we have
        
        .. math::
            \frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)} = \prod_i{p\left({\mathbf{m}_i^{k+1}}\right)}
                         
        and
        
        .. math::
            \frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)} =
            \frac{1}{k+1} \frac{\prod_i{p\left({\mathbf{m}_i^{k+1}}\right)}}{\frac{1}{(k+1)}} =
            \frac{1}{\prod_i{p\left({\mathbf{m}_i^{k+1}}\right)}},
            
        where :math:`k` denotes the number of dimensions in the parameter space 
        prior to the perturbation and the subscript :math:`i` the 
        :math:`i`\ th free parameter. :math:`\mathbf{m}_i^{k+1}` denotes the
        newly added value in the :math:`i`\ th parameter as a result of the birth
        of a new dimension. (Note that in this case the new value is added
        by sampling from the prior.)
        
        Moreover, it can be shown that in this cases the Jacobian determinant
        is equal to one. It follows that
                
        .. math::
            \alpha_{p} = 
            \frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}
            \frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}
            = \prod_i{p\left({\mathbf{m}_i^{k+1}}\right)} \frac{1}{\prod_i{p\left({\mathbf{m}_i^{k+1}}\right)}}
            = 1,
        
        and :math:`\log(\alpha_{p}) = 0`.
        
        Parameters
        ----------
        ParameterSpaceState
            initial parameter space state

        Returns
        -------
        ParameterSpaceState
            new parameter space state
        Number
            log of the partial acceptance probability, 
            :math:`\alpha_{p} = \log(
            \frac{p({\bf m'})}{p({\bf m})}
            \frac{q\left({\bf m} 
            \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}
            \lvert \mathbf{J} \rvert)`
        """
        n_dims = ps_state.n_dimensions
        if n_dims == self._n_dimensions_max:
            raise DimensionalityException("Birth")
        i_insert = random.randint(0, n_dims)
        new_param_values = dict()
        for param_name, param_vals in ps_state.param_values.items():
            new_param_values[param_name] = insert_scalar(
                param_vals, 
                i_insert, 
                self.parameters[param_name].initialize()
            )
        new_state = ParameterSpaceState(n_dims+1, new_param_values)
        prob_ratio = 0
        return new_state, prob_ratio
    
    def death(self, ps_state: ParameterSpaceState) -> Tuple[ParameterSpaceState, float]:
        r"""removes a dimension from the given parameter space and returns the
        thus obtained new state along with the log of the corresponding partial 
        acceptance probability,
        
        .. math::
            \underbrace{\alpha_{p}}_{\begin{array}{c} \text{Partial} \\ \text{acceptance} \\ \text{probability} \end{array}} = 
            \underbrace{\frac{p\left({\bf m'}\right)}{p\left({\bf m}\right)}}_{\text{Prior ratio}} 
            \underbrace{\frac{q\left({\bf m} \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}}_{\text{Proposal ratio}}  
            \underbrace{\lvert \mathbf{J} \rvert}_{\begin{array}{c} \text{Jacobian} \\ \text{determinant} \end{array}},
        
        Parameters
        ----------
        ParameterSpaceState
            initial parameter space state

        Returns
        -------
        ParameterSpaceState
            new parameter space state
        Number
            log of the partial acceptance probability, 
            :math:`\alpha_{p} = \log(
            \frac{p({\bf m'})}{p({\bf m})}
            \frac{q\left({\bf m} 
            \mid {\bf m'}\right)}{q\left({\bf m'} \mid {\bf m}\right)}
            \lvert \mathbf{J} \rvert)`
        """
        n_dims = ps_state.n_dimensions
        if n_dims == self._n_dimensions_min:
            raise DimensionalityException("Death")
        i_to_remove = random.randint(0, n_dims-1)
        new_param_values = dict()
        for param_name, param_vals in ps_state.param_values.items():
            new_param_values[param_name] = delete(param_vals, i_to_remove)
        new_state = ParameterSpaceState(n_dims-1, new_param_values)
        prob_ratio = 0
        return new_state, prob_ratio
    
    def _init_perturbation_funcs(self):
        self._perturbation_funcs = []
        if self.parameters:
            self._perturbation_funcs.append(
                ParamPerturbation(self.name, list(self.parameters.values()))
            )
        if self.trans_d:
            self._perturbation_funcs.append(BirthPerturbation(self))
            self._perturbation_funcs.append(DeathPerturbation(self))

    def _repr_dict(self) -> dict:
        attr_to_show = {"name": self.name, "parameters": self.parameters.keys()}
        if self.trans_d:
            attr_to_show["n_dimensions_min"] = self._n_dimensions_min
            attr_to_show["n_dimensions_max"] = self._n_dimensions_max
            attr_to_show["n_dimensions_init_range"] = self._n_dimensions_init_range
        else:
            attr_to_show["n_dimensions"] = self._n_dimensions
        return attr_to_show

    def __repr__(self) -> str:
        attr_to_show = self._repr_dict()
        string = "%s(" % attr_to_show["name"]
        for k, v in attr_to_show.items():
            if k == "name":
                continue
            string += "%s=%s, " % (k, v)
        string = string[:-2]
        return string + ")"
