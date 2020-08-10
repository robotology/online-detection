import logging

from .ivos_eval import do_ivos_evaluation


def ivos_evaluation(dataset, predictions, output_folder, box_only, iou_types, expected_results, expected_results_sigma_tol, draw_preds, is_target_task=False):

    logger = logging.getLogger("maskrcnn_benchmark.inference")
    if box_only:
        logger.warning("icw evaluation doesn't support box_only, ignored.")
    logger.info("performing icw evaluation, ignored iou_types.")

    return do_ivos_evaluation(
        dataset=dataset,
        predictions=predictions,
        output_folder=output_folder,
        draw_preds=draw_preds,
        logger=logger,
        is_target_task=is_target_task,
    )
