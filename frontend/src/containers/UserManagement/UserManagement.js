import React from 'react';
import { connect } from 'react-redux';

import { login } from 'store/modules/auth';
import { showModal } from 'store/modules/userLogin';

import { UserManagementUI } from 'components/siteComponents';


const mapStateToProps = (outerState) => {
  const state = outerState.app;
  return {
    auth: state.get('auth'),
    open: state.getIn(['userLogin', 'open'])
  };
};

const mapDispatchToProps = (dispatch) => {
  return {
    loginFn: data => dispatch(login(data)),
    showModal: b => dispatch(showModal(b))
  };
};


export default connect(
  mapStateToProps,
  mapDispatchToProps
)(UserManagementUI);
