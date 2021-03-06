#
#    This file is part of awebox.
#
#    awebox -- A modeling and optimization framework for multi-kite AWE systems.
#    Copyright (C) 2017-2019 Jochem De Schutter, Rachel Leuthold, Moritz Diehl,
#                            ALU Freiburg.
#    Copyright (C) 2018-2019 Thilo Bronnenmeyer, Kiteswarms Ltd.
#    Copyright (C) 2016      Elena Malz, Sebastien Gros, Chalmers UT.
#
#    awebox is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 3 of the License, or (at your option) any later version.
#
#    awebox is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with awebox; if not, write to the Free Software Foundation,
#    Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
#
'''
specific aerodynamics for a 6dof kite
_python-3.5 / casadi-3.4.5
- author: rachel leuthold, alu-fr 2017-20
'''

import casadi.tools as cas

import awebox.tools.vector_operations as vect_op
import awebox.mdl.aero.indicators as indicators
import numpy as np

import awebox.mdl.aero.kite_dir.stability_derivatives as stability_derivatives
import awebox.mdl.aero.kite_dir.frames as frames
import awebox.mdl.aero.kite_dir.tools as tools

from awebox.logger.logger import Logger as awelogger



def get_outputs(options, atmos, wind, variables, outputs, parameters, architecture):

    xd = variables['xd']
    elevation_angle = indicators.get_elevation_angle(xd)

    b_ref = parameters['theta0', 'geometry', 'b_ref']
    c_ref = parameters['theta0', 'geometry', 'c_ref']
    s_ref = parameters['theta0', 'geometry', 's_ref']
    reference_lengths = cas.diag(cas.vertcat(b_ref, c_ref, b_ref))

    kite_nodes = architecture.kite_nodes
    for kite in kite_nodes:
        parent = architecture.parent_map[kite]

        q = xd['q' + str(kite) + str(parent)]
        kite_dcm = cas.reshape(xd['r' + str(kite) + str(parent)], (3, 3))
        ehat1 = kite_dcm[:, 0]
        ehat2 = kite_dcm[:, 1]

        vec_u_eff = tools.get_u_eff_in_earth_frame(options, variables, wind, kite, architecture)
        u_eff = vect_op.smooth_norm(vec_u_eff)
        rho = atmos.get_density(q[2])
        q_eff = 0.5 * rho * cas.mtimes(vec_u_eff.T, vec_u_eff)

        f_aero_body = tools.get_f_aero_var(variables, kite, parent, parameters)
        coeff_body = f_aero_body / q_eff / s_ref
        CA = coeff_body[0]
        CY = coeff_body[1]
        CN = coeff_body[2]

        f_aero_wind = frames.from_body_to_wind(vec_u_eff, kite_dcm, f_aero_body)
        wind_dcm = frames.get_wind_dcm(vec_u_eff, kite_dcm)
        f_drag = f_aero_wind[0] * wind_dcm[:, 0]
        f_side = f_aero_wind[1] * wind_dcm[:, 1]
        f_lift = f_aero_wind[2] * wind_dcm[:, 2]

        coeff_wind = f_aero_wind / q_eff / s_ref
        CD = coeff_wind[0]
        CS = coeff_wind[1]
        CL = coeff_wind[2]

        f_aero_earth = frames.from_body_to_earth(kite_dcm, f_aero_body)
        f_aero = f_aero_earth

        m_aero = tools.get_m_aero_var(variables, kite, parent, parameters)
        CM = cas.mtimes(cas.inv(reference_lengths), m_aero) / q_eff / s_ref
        Cl = CM[0]
        Cm = CM[1]
        Cn = CM[2]

        aero_coefficients = {}
        aero_coefficients['CD'] = CD
        aero_coefficients['CS'] = CS
        aero_coefficients['CL'] = CL
        aero_coefficients['CA'] = CA
        aero_coefficients['CY'] = CY
        aero_coefficients['CN'] = CN
        aero_coefficients['Cl'] = Cl
        aero_coefficients['Cm'] = Cm
        aero_coefficients['Cn'] = Cn

        outputs = indicators.collect_kite_aerodynamics_outputs(options, atmos, vec_u_eff, u_eff, aero_coefficients,
                                                               f_aero, f_lift, f_drag, f_side, m_aero,
                                                               ehat1, ehat2, kite_dcm, q, kite,
                                                               outputs, parameters)
        outputs = indicators.collect_environmental_outputs(atmos, wind, q, kite, outputs)
        outputs = indicators.collect_aero_validity_outputs(options, xd, vec_u_eff, kite, parent, outputs, parameters)
        outputs = indicators.collect_local_performance_outputs(options, atmos, wind, variables, CL, CD, elevation_angle,
                                                               vec_u_eff, kite, parent, outputs, parameters)
        outputs = indicators.collect_power_balance_outputs(variables, kite, outputs, architecture)

    return outputs






def get_force_resi(options, variables, atmos, wind, architecture, parameters):

    aero_coeff_ref_velocity = options['aero']['aero_coeff_ref_velocity']
    if aero_coeff_ref_velocity == 'app':
        force_and_moment_fun = get_force_and_moment_fun_from_u_app_alone_in_kite_frame(options, parameters)
    elif aero_coeff_ref_velocity == 'eff':
        force_and_moment_fun = get_force_and_moment_fun_from_u_eff_in_kite_frame(options, parameters)
    else:
        awelogger.logger.error('unrecognized velocity field associated with stability derivative computation')

    surface_control = options['surface_control']

    resi = []
    for kite in architecture.kite_nodes:

        parent = architecture.parent_map[kite]
        f_aero_var = tools.get_f_aero_var(variables, kite, parent, parameters)
        m_aero_var = tools.get_m_aero_var(variables, kite, parent, parameters)

        if int(surface_control) == 0:
            delta = variables['u']['delta' + str(kite) + str(parent)]
        elif int(surface_control) == 1:
            delta = variables['xd']['delta' + str(kite) + str(parent)]

        omega = variables['xd']['omega' + str(kite) + str(parent)]
        kite_dcm = cas.reshape(variables['xd']['r' + str(kite) + str(parent)], (3, 3))

        q = variables['xd']['q' + str(kite) + str(parent)]
        rho = atmos.get_density(q[2])

        if aero_coeff_ref_velocity == 'app':
            vec_u = tools.get_u_app_alone_in_body_frame(options, variables, atmos, wind, kite, kite_dcm, architecture, parameters)
        elif aero_coeff_ref_velocity == 'eff':
            vec_u = tools.get_u_eff_in_body_frame(options, variables, wind, kite, kite_dcm, architecture)

        force_and_moment_in_body_frame = force_and_moment_fun(vec_u, omega, delta, rho)
        f_body_found = force_and_moment_in_body_frame[:3]
        m_found = force_and_moment_in_body_frame[3:]

        # f_found = frames.from_body_to_earth(kite_dcm, f_body_found)
        f_found = f_body_found

        f_scale = tools.get_f_scale(parameters)
        m_scale = tools.get_m_scale(parameters)

        resi_f_kite = (f_aero_var - f_found) / f_scale
        resi_m_kite = (m_aero_var - m_found) / m_scale

        resi = cas.vertcat(resi, resi_f_kite, resi_m_kite)

    return resi







def get_force_and_moment_fun_from_u_eff_in_kite_frame(options, parameters):

    # creates a casadi function that finds the force and moment, all calculations in kite-body reference frame.

    delta_sym = cas.SX.sym('delta_sym', 3)
    vec_u_eff_sym = cas.SX.sym('vec_u_eff_sym', 3)
    omega_sym = cas.SX.sym('omega_sym', 3)
    rho_sym = cas.SX.sym('rho_sym')

    force_and_moment = get_force_and_moment_from_u_eff_in_kite_frame(options, parameters, vec_u_eff_sym, omega_sym, delta_sym,
                                                        rho_sym)

    force_and_moment_fun = cas.Function('force_and_moment_fun', [vec_u_eff_sym, omega_sym, delta_sym, rho_sym], [force_and_moment])

    return force_and_moment_fun


def get_force_and_moment_from_u_eff_in_kite_frame(options, parameters, vec_u_eff_sym, omega_sym, delta_sym, rho_sym):

    dcm_body_frame = cas.DM.eye(3)
    alpha_eff = indicators.get_alpha(vec_u_eff_sym, dcm_body_frame)
    beta_eff = indicators.get_beta(vec_u_eff_sym, dcm_body_frame)

    CF, CM = stability_derivatives.stability_derivatives(options, alpha_eff, beta_eff, vec_u_eff_sym, dcm_body_frame, omega_sym, delta_sym, parameters)

    u_eff_sq = cas.mtimes(vec_u_eff_sym.T, vec_u_eff_sym)
    dynamic_pressure = 1. / 2. * rho_sym * u_eff_sq
    planform_area = parameters['theta0', 'geometry', 's_ref']

    force = CF * dynamic_pressure * planform_area

    b_ref = parameters['theta0', 'geometry', 'b_ref']
    c_ref = parameters['theta0', 'geometry', 'c_ref']
    reference_lengths = cas.diag(cas.vertcat(b_ref, c_ref, b_ref))

    moment = dynamic_pressure * planform_area * cas.mtimes(reference_lengths, CM)

    force_and_moment = cas.vertcat(force, moment)

    return force_and_moment








def get_force_and_moment_fun_from_u_app_alone_in_kite_frame(options, parameters):

    # creates a casadi function that finds the force and moment, all calculations in kite-body reference frame.

    delta_sym = cas.SX.sym('delta_sym', 3)
    vec_u_app_alone_sym = cas.SX.sym('vec_u_app_alone_sym', 3)
    omega_sym = cas.SX.sym('omega_sym', 3)
    rho_sym = cas.SX.sym('rho_sym')

    force_and_moment = get_force_and_moment_from_u_app_alone_in_kite_frame(options, parameters, vec_u_app_alone_sym, omega_sym, delta_sym,
                                                        rho_sym)

    force_and_moment_fun = cas.Function('force_and_moment_fun', [vec_u_app_alone_sym, omega_sym, delta_sym, rho_sym], [force_and_moment])

    return force_and_moment_fun


def get_force_and_moment_from_u_app_alone_in_kite_frame(options, parameters, vec_u_app_alone_sym, omega_sym, delta_sym, rho_sym):

    dcm_body_frame = cas.DM.eye(3)
    alpha_app_alone = indicators.get_alpha(vec_u_app_alone_sym, dcm_body_frame)
    beta_app_alone = indicators.get_beta(vec_u_app_alone_sym, dcm_body_frame)

    CF, CM = stability_derivatives.stability_derivatives(options, alpha_app_alone, beta_app_alone, vec_u_app_alone_sym, dcm_body_frame, omega_sym, delta_sym, parameters)

    u_app_sq = cas.mtimes(vec_u_app_alone_sym.T, vec_u_app_alone_sym)
    dynamic_pressure = 1. / 2. * rho_sym * u_app_sq
    planform_area = parameters['theta0', 'geometry', 's_ref']

    force = CF * dynamic_pressure * planform_area

    b_ref = parameters['theta0', 'geometry', 'b_ref']
    c_ref = parameters['theta0', 'geometry', 'c_ref']
    reference_lengths = cas.diag(cas.vertcat(b_ref, c_ref, b_ref))

    moment = dynamic_pressure * planform_area * cas.mtimes(reference_lengths, CM)

    force_and_moment = cas.vertcat(force, moment)

    return force_and_moment





def get_wingtip_position(kite, model, variables, parameters, ext_int):
    parent_map = model.architecture.parent_map

    xd = model.variables_dict['xd'](variables['xd'])

    if ext_int == 'ext':
        span_sign = 1.
    elif ext_int == 'int':
        span_sign = -1.
    else:
        awelogger.logger.error('wing side not recognized for 6dof kite.')

    parent = parent_map[kite]

    name = 'q' + str(kite) + str(parent)
    q_unscaled = xd[name]
    scale = model.scaling['xd'][name]
    q = q_unscaled * scale

    kite_dcm = cas.reshape(xd['kite_dcm' + str(kite) + str(parent)], (3, 3))
    ehat_span = kite_dcm[:, 1]

    b_ref = parameters['theta0','geometry','b_ref']

    wingtip_position = q + ehat_span * span_sign * b_ref / 2.

    return wingtip_position
