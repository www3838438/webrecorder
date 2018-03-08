import React from 'react';
import { connect } from 'react-redux';

import { selectCollection } from 'store/modules/user';

import { UploadUI } from 'components/siteComponents';


const mapStateToProps = ({ app }) => {
  return {
    activeCollection: app.getIn(['user', 'activeCollection'])
  };
};

const mapDispatchToProps = (dispatch) => {
  return {
    setColl: coll => dispatch(selectCollection(coll))
  };
};


export default connect(
  mapStateToProps,
  mapDispatchToProps
)(UploadUI);
