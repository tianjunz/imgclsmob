import argparse
import time
import logging

import mxnet as mx

from common.logger_utils import initialize_logging
from gluon.utils import prepare_mx_context, prepare_model, calc_net_weight_count, validate1
from gluon.model_stats import measure_model
from gluon.cifar import add_dataset_parser_arguments
from gluon.cifar import batch_fn
from gluon.cifar import get_val_data_source


def parse_args():
    parser = argparse.ArgumentParser(
        description='Evaluate a model for image classification (Gluon/CIFAR/SVHN)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--dataset',
        type=str,
        default="CIFAR10",
        help='dataset name. options are CIFAR10, CIFAR100, and SVHN')

    args, _ = parser.parse_known_args()
    add_dataset_parser_arguments(parser, args.dataset)

    parser.add_argument(
        '--model',
        type=str,
        required=True,
        help='type of model to use. see model_provider for options.')
    parser.add_argument(
        '--use-pretrained',
        action='store_true',
        help='enable using pretrained model from gluon.')
    parser.add_argument(
        '--dtype',
        type=str,
        default='float32',
        help='data type for training. default is float32')
    parser.add_argument(
        '--resume',
        type=str,
        default='',
        help='resume from previously saved parameters if not None')
    parser.add_argument(
        '--calc-flops',
        dest='calc_flops',
        action='store_true',
        help='calculate FLOPs')
    parser.add_argument(
        '--calc-flops-only',
        dest='calc_flops_only',
        action='store_true',
        help='calculate FLOPs without quality estimation')

    parser.add_argument(
        '--num-gpus',
        type=int,
        default=0,
        help='number of gpus to use.')
    parser.add_argument(
        '-j',
        '--num-data-workers',
        dest='num_workers',
        default=4,
        type=int,
        help='number of preprocessing workers')

    parser.add_argument(
        '--batch-size',
        type=int,
        default=512,
        help='training batch size per device (CPU/GPU).')

    parser.add_argument(
        '--save-dir',
        type=str,
        default='',
        help='directory of saved models and log-files')
    parser.add_argument(
        '--logging-file-name',
        type=str,
        default='train.log',
        help='filename of training log')

    parser.add_argument(
        '--log-packages',
        type=str,
        default='mxnet',
        help='list of python packages for logging')
    parser.add_argument(
        '--log-pip-packages',
        type=str,
        default='mxnet-cu92',
        help='list of pip packages for logging')
    args = parser.parse_args()
    return args


def test(net,
         val_data,
         data_source_needs_reset,
         dtype,
         ctx,
         input_image_size,
         in_channels,
         calc_weight_count=False,
         calc_flops=False,
         calc_flops_only=True,
         extended_log=False):
    if not calc_flops_only:
        accuracy_metric = mx.metric.Accuracy()
        tic = time.time()
        err_val = validate1(
            accuracy_metric=accuracy_metric,
            net=net,
            val_data=val_data,
            batch_fn=batch_fn,
            data_source_needs_reset=data_source_needs_reset,
            dtype=dtype,
            ctx=ctx)
        if extended_log:
            logging.info('Test: err={err:.4f} ({err})'.format(
                err=err_val))
        else:
            logging.info('Test: err={err:.4f}'.format(
                err=err_val))
        logging.info('Time cost: {:.4f} sec'.format(
            time.time() - tic))

    if calc_weight_count:
        weight_count = calc_net_weight_count(net)
        if not calc_flops:
            logging.info("Model: {} trainable parameters".format(weight_count))
    if calc_flops:
        num_flops, num_macs, num_params = measure_model(net, in_channels, input_image_size, ctx[0])
        assert (not calc_weight_count) or (weight_count == num_params)
        stat_msg = "Params: {params} ({params_m:.2f}M), FLOPs: {flops} ({flops_m:.2f}M)," \
                   " FLOPs/2: {flops2} ({flops2_m:.2f}M), MACs: {macs} ({macs_m:.2f}M)"
        logging.info(stat_msg.format(
            params=num_params, params_m=num_params / 1e6,
            flops=num_flops, flops_m=num_flops / 1e6,
            flops2=num_flops / 2, flops2_m=num_flops / 2 / 1e6,
            macs=num_macs, macs_m=num_macs / 1e6))


def main():
    args = parse_args()

    _, log_file_exist = initialize_logging(
        logging_dir_path=args.save_dir,
        logging_file_name=args.logging_file_name,
        script_args=args,
        log_packages=args.log_packages,
        log_pip_packages=args.log_pip_packages)

    ctx, batch_size = prepare_mx_context(
        num_gpus=args.num_gpus,
        batch_size=args.batch_size)

    net = prepare_model(
        model_name=args.model,
        use_pretrained=args.use_pretrained,
        pretrained_model_file_path=args.resume.strip(),
        dtype=args.dtype,
        classes=args.num_classes,
        in_channels=args.in_channels,
        do_hybridize=(not args.calc_flops),
        ctx=ctx)
    input_image_size = net.in_size if hasattr(net, 'in_size') else (32, 32)

    val_data = get_val_data_source(
        dataset_name=args.dataset,
        dataset_dir=args.data_dir,
        batch_size=batch_size,
        num_workers=args.num_workers)

    assert (args.use_pretrained or args.resume.strip() or args.calc_flops_only)
    test(
        net=net,
        val_data=val_data,
        data_source_needs_reset=False,
        dtype=args.dtype,
        ctx=ctx,
        input_image_size=input_image_size,
        in_channels=args.in_channels,
        # calc_weight_count=(not log_file_exist),
        calc_weight_count=True,
        calc_flops=args.calc_flops,
        calc_flops_only=args.calc_flops_only,
        extended_log=True)


if __name__ == '__main__':
    main()
