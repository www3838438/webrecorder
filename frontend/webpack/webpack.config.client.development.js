import autoprefixer from 'autoprefixer';
import webpack from 'webpack';
import fs from 'fs';
import merge from 'webpack-merge';
import config from '../src/config';

import getBaseConfig from './webpack.config.client';


const baseConfig = getBaseConfig({
  development: true,
  css_bundle: true
});

const babelrc = fs.readFileSync('./.babelrc');
let babelrcObject = {};

try {
  babelrcObject = JSON.parse(babelrc);
} catch (err) {
  console.error('==> ERROR: Error parsing your .babelrc.');
  console.error(err);
}

const babelrcObjectDevelopment = (babelrcObject.env && babelrcObject.env.development) || {};

// merge global and dev-only plugins
let combinedPlugins = babelrcObject.plugins || [];
combinedPlugins = combinedPlugins.concat(babelrcObjectDevelopment.plugins);

const babelLoaderQuery = Object.assign({}, babelrcObject, babelrcObjectDevelopment, { plugins: combinedPlugins });
delete babelLoaderQuery.env;

babelLoaderQuery.presets = babelLoaderQuery.presets.map((v) => {
  return v === 'es2015' ? ['es2015', { modules: false }] : v;
});

const host = '127.0.0.1';
const port = Number(config.port) + 1;

const devConfig = {
  entry: {
    main: [
      'react-hot-loader/patch',
      `webpack-hot-middleware/client?path=http://${host}:${port}/__webpack_hmr&quiet=true`,
      './src/client.js',
      './config/polyfills',
      'bootstrap-loader/extractStyles'
    ]
  },

  output: {
    publicPath: `http://${host}:${port}/dist/`
  },

  module: {
    rules: [
      {
        test: /\.(js|jsx)?$/,
        exclude: /node_modules/,
        loader: 'babel-loader'
      },
      {
        test: /\.scss$/,
        use: [
          'style-loader',
          'css-loader',
          {
            loader: 'postcss-loader',
            options: {
              plugins: () => {
                return [
                  autoprefixer({
                    browsers: [
                      '>1%',
                      'last 4 versions',
                      'Firefox ESR',
                      'not ie < 9',
                    ]
                  })
                ];
              }
            }
          },
          'sass-loader'
        ]
      }
    ]
  },

  plugins: [
    new webpack.HotModuleReplacementPlugin(),
    new webpack.DefinePlugin({
      __CLIENT__: true,
      __SERVER__: false,
      __DEVELOPMENT__: true,
      __DEVTOOLS__: true,
      __PLAYER__: false
    }),
  ]
};

export default merge(baseConfig, devConfig);
