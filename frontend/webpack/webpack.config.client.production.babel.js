import path from 'path';
import webpack from 'webpack';
import merge from 'webpack-merge';

import ExtractTextPlugin from 'extract-text-webpack-plugin';
import CleanPlugin from 'clean-webpack-plugin';

import getBaseConfig from './webpack.config.client';

const projectRootPath = path.resolve(__dirname, '../');
const assetsPath = path.resolve(projectRootPath, './static/dist');
const baseConfig = getBaseConfig({ development: false });

const prodConfig = {
  devtool: 'source-map',

  entry: {
    main: [
      './config/polyfills',
      'bootstrap-loader/extractStyles',
      './src/client.js'
    ]
  },

  output: {
    filename: '[name]-[chunkhash].js',
    publicPath: '/static/'
  },

  plugins: [
    new CleanPlugin([assetsPath], { root: projectRootPath }),

    new ExtractTextPlugin({
      filename: '[name]-[chunkhash].css',
      allChunks: true
    }),

    new webpack.DefinePlugin({
      __CLIENT__: true,
      __SERVER__: false,
      __DEVELOPMENT__: false,
      __DEVTOOLS__: false,
      __PLAYER__: false
    }),

    // optimizations
    new webpack.optimize.UglifyJsPlugin({
      compress: {
        unused: true,
        warnings: false,
        dead_code: true,
        drop_console: true
      }
    })
  ]
};

export default merge(baseConfig, prodConfig);
