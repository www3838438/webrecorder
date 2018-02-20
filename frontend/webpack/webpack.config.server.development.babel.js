import autoprefixer from 'autoprefixer';
import merge from 'webpack-merge';
import webpack from 'webpack';
import { port } from '../src/config';
import baseConfig from './webpack.config.server';

const host = '127.0.0.1';
const assetPort = Number(port) + 1;

const config = {
  output: {
    publicPath: `http://${host}:${assetPort}/dist/`
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
    new webpack.DefinePlugin({
      __CLIENT__: false,
      __SERVER__: true,
      __DEVELOPMENT__: true,
      __DEVTOOLS__: true,
      __PLAYER__: false
    }),
  ]
};

export default merge(baseConfig, config);
